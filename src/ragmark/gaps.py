"""Gap detection — the policy migrates INTO ragmark (the-vault#143, decision 2).

``rank_pairs`` reimplements graphmark v0.9.1's ``metrics.gaps()``
(``src/graphmark/metrics.py:179-251``, the version ``uv.lock`` pins)
faithfully. Deliberate differences from that source:

1. No ``sig`` in the output — ``rank_pairs`` returns bare ``(a, b, score)``
   tuples; a caller that needs the dismissal-store key recomputes it (see
   the module-private ``_sig`` below).
2. No path-prefix exclusion — no ``exclude_prefixes`` parameter.

A later slice appends context gating as difference 3.

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

from ragmark.config import RagmarkConfig

# Banding policy, verbatim from graphmark metrics.py at migration decision time.
GAPS_DEFAULT_THRESHOLD = 0.6
GAPS_DEFAULT_MAX_SCORE = 0.92
GAPS_DEFAULT_K = 8
GAPS_DEFAULT_HUB_DEGREE = 40


def _sig(a: str, b: str) -> str:
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

    def _rank_key(item: tuple[str, str, float]) -> tuple[bool, bool, float, str, str]:
        a, b, score = item
        hubby = _is_hub(a) or _is_hub(b)
        cross = a.split("/", 1)[0] != b.split("/", 1)[0]
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
    raise NotImplementedError("build slice: gap policy migration (the-vault#143 d2)")
