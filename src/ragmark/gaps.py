"""Gap detection — the policy migrates INTO ragmark (the-vault#143, decision 2).

``rank_pairs`` reimplements graphmark v0.10.0's ``metrics.gaps()``
(``src/graphmark/metrics.py``, the version ``uv.lock`` pins)
faithfully. Deliberate differences from that source:

1. No ``sig`` in the output — ``rank_pairs`` returns bare ``(a, b, score)``
   tuples; a caller that needs the dismissal-store key recomputes it (see
   the module-private ``_sig`` below).
2. No path-prefix exclusion — no ``exclude_prefixes`` parameter.
3. Context gating — ``gaps()`` filters its targets, every similarity candidate, and every
   dismissal record through ``gate.filter_visible``, so a note outside the active machine
   context is never scored, hashed, or returned.
4. Corpus scope — the shared graph adapter excludes configured non-content before
   names and aliases are resolved (ragmark#94's approved owner corpus policy).

What stays in graphmark: the deterministic graph itself — this module
consumes graphmark for structure (degree/hub facts, linked-pair queries) and
ragmark's own note-level similarity for scores. graphmark's ``gaps()``
deprecates only AFTER this lands (absorption staging puts the two-repo step
LAST — the-vault#140, decision 10; deprecation path recorded on graphmark's
ROADMAP, graphmark#197).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import Path

from graphmark.graph import VaultGraph
from graphmark.interfaces import Similarity

from ragmark import _graph, dismiss, gate, search
from ragmark.config import RagmarkConfig
from ragmark.store import IndexStore

# Banding policy, verbatim from graphmark metrics.py at migration decision time.
GAPS_DEFAULT_THRESHOLD = 0.6
GAPS_DEFAULT_MAX_SCORE = 0.92
GAPS_DEFAULT_K = 8
GAPS_DEFAULT_HUB_DEGREE = 40

# graphmark's dismissal-store default, relative to the vault root.
_DEFAULT_DISMISSAL_STORE = ".claude/data/connect-dismissed.json"


def _sig(a: str, b: str) -> str:
    # Identical to ``dismiss.weaklink_sig`` (pinned by tests/test_gaps.py); kept local because
    # the source-scan test bans ``weaklink_sig`` references in this module.
    return "weaklink|" + "|".join(sorted([a, b]))


def _degrees(graph: VaultGraph) -> dict[str, int]:
    """Undirected simple-graph degree per node, self-loops counting 2.

    Mirrors graphmark's private ``metrics._undirected(graph).degree(n)``: nodes are
    ``graph.nodes``, edges are every ``(src, dst)`` in ``graph.out_links`` collapsed to an
    unordered, deduplicated edge set (a simple graph has no parallel edges, so a mutual
    wikilink pair contributes one edge, not two).
    """
    degrees: dict[str, int] = dict.fromkeys(graph.nodes, 0)
    edges: set[tuple[str, str]] = set()
    for src, dsts in graph.out_links.items():
        for dst in dsts:
            edges.add((src, dst) if src <= dst else (dst, src))
    for u, v in edges:
        if u == v:
            degrees[u] = degrees.get(u, 0) + 2
        else:
            degrees[u] = degrees.get(u, 0) + 1
            degrees[v] = degrees.get(v, 0) + 1
    return degrees


def rank_pairs(
    graph: VaultGraph,
    similar_fn: Similarity,
    *,
    threshold: float,
    max_score: float,
    k: int,
    hub_degree: int,
    dismissed: Collection[str],
    targets: Sequence[str],
) -> list[tuple[str, str, float]]:
    """Ranked unlinked-but-similar note pairs among ``targets`` (see module contract)."""
    degrees = _degrees(graph)

    def _is_hub(rel: str) -> bool:
        return rel in degrees and degrees[rel] >= hub_degree

    dedup: dict[frozenset[str], tuple[str, str, float]] = {}

    for rel in targets:
        linked = graph.out_links.get(rel, set()) | graph.back_links.get(rel, set())

        for other, score in similar_fn(rel, k):
            if other == rel:
                continue
            if other in linked:
                continue
            if not (threshold <= score <= max_score):
                continue

            sig = _sig(rel, other)
            if sig in dismissed:
                continue

            key = frozenset({rel, other})
            if key not in dedup or score > dedup[key][2]:
                dedup[key] = (rel, other, score)
            elif score == dedup[key][2]:
                # Equal-score duplicate: store the pair sorted so the result does not
                # depend on target iteration order (graphmark v0.10.0).
                dedup[key] = (*sorted((rel, other)), score)

    def _top(path: str) -> str:
        # A root-level note has no top-level folder ("" — graphmark v0.10.0), so it is
        # cross-folder against every foldered note.
        head, sep, _ = path.partition("/")
        return head if sep else ""

    def _rank_key(item: tuple[str, str, float]) -> tuple[bool, bool, float, str, str]:
        a, b, score = item
        hubby = _is_hub(a) or _is_hub(b)
        cross = _top(a) != _top(b)
        return (hubby, not cross, -score, a, b)

    ranked = sorted(dedup.values(), key=_rank_key)
    return [(a, b, round(score, 4)) for a, b, score in ranked]


def gaps(
    *,
    config: RagmarkConfig,
    threshold: float = GAPS_DEFAULT_THRESHOLD,
    max_score: float = GAPS_DEFAULT_MAX_SCORE,
    k: int = GAPS_DEFAULT_K,
    hub_degree: int = GAPS_DEFAULT_HUB_DEGREE,
    dismissal_store: Path | None = None,
) -> list[tuple[str, str, float]]:
    """Ranked unlinked-but-similar note pairs (see module contract)."""
    graph = _graph.build_graph(config)

    store = IndexStore(config.index_dir)
    # Both checks are needed: ``search.similar_notes`` returns [] on a missing index, and
    # ``IndexStore.connect`` would create the directory.
    if not store.db_path.exists() or not store.vectors_path.exists():
        raise FileNotFoundError(
            f"no ragmark index at {config.index_dir}; run `ragmark index` first"
        )

    targets = gate.filter_visible(list(graph.nodes), config)

    def similar_fn(rel: str, limit: int) -> list[tuple[str, float]]:
        try:
            candidates = search.similar_notes(rel, limit, config=config, store=store)
        except gate.VaultAccessError:
            # A note can become unavailable between graph construction and search.
            # Only access refusals are skipped; index and computation errors propagate.
            return []
        visible = set(gate.filter_visible([other for other, _ in candidates], config))
        return [(other, score) for other, score in candidates if other in visible]

    store_path = config.vault_root / (dismissal_store or _DEFAULT_DISMISSAL_STORE)
    records = dismiss.load_dismissed(config.vault_root, path=str(store_path))
    dismissed: set[str] = set()
    root = config.vault_root
    for sig, record in records.items():
        # Malformed or out-of-vault records are skipped, as graphmark v0.10.0's
        # ``active_dismissed_sigs`` does.
        if not isinstance(record, dict):
            continue
        a, b, a_hash, b_hash = (
            record.get("a"),
            record.get("b"),
            record.get("a_hash"),
            record.get("b_hash"),
        )
        if not all(isinstance(v, str) and v for v in (a, b, a_hash, b_hash)):
            continue
        if not dismiss._resolves_within(root, a) or not dismiss._resolves_within(root, b):
            continue
        if len(gate.filter_visible([a, b], config)) != 2:
            continue
        a_path, b_path = root / a, root / b
        if (
            a_path.is_file()
            and b_path.is_file()
            and dismiss.content_hash(a_path) == a_hash
            and dismiss.content_hash(b_path) == b_hash
        ):
            dismissed.add(sig)

    return rank_pairs(
        graph,
        similar_fn,
        threshold=threshold,
        max_score=max_score,
        k=k,
        hub_degree=hub_degree,
        dismissed=dismissed,
        targets=targets,
    )
