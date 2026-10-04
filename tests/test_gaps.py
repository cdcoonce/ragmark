"""Parity tests for ``rank_pairs`` against graphmark v0.10.0's ``metrics.gaps()``.

Fixture vault (`tests/fixtures/gaps/vault/`): band-edge probes (lo/hi exactly on
threshold/max_score, below/above just outside), a real wikilink (linkA -> linkB) for
already-linked filtering in both directions, a hub note (`hubn.md`, made a hub only by an
in-memory self-loop injected after `graphmark.build`), a non-hub pair, same- vs.
cross-folder ties, a duplicate unordered pair at two scores, a dismissed pair, an equal-score
reciprocal tie, and a note offered as similar to itself.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import re
import textwrap
from collections.abc import Callable
from pathlib import Path

import graphmark
import graphmark.metrics
import pytest

from ragmark import dismiss, gaps, gate, search
from ragmark.config import CONTEXT_FILE, RagmarkConfig

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "gaps" / "vault"

THRESHOLD = 0.6
MAX_SCORE = 0.92
K = 10
HUB_DEGREE = 2

SIMILAR: dict[str, list[tuple[str, float]]] = {
    "lo.md": [("lo_partner.md", 0.6)],
    "below.md": [("below_partner.md", 0.59)],
    "hi.md": [("hi_partner.md", 0.92)],
    "above.md": [("above_partner.md", 0.93)],
    "linkA.md": [("linkB.md", 0.75)],
    "linkB.md": [("linkA.md", 0.75)],
    "hubn.md": [("hubpartner.md", 0.85)],
    "nonhub_x.md": [("nonhub_y.md", 0.65)],
    "same/one.md": [("same/two.md", 0.70)],
    "same/three.md": [("other/four.md", 0.70)],
    "dup_p.md": [("dup_q.md", 0.70)],
    "dup_q.md": [("dup_p.md", 0.75)],
    "dismiss_d1.md": [("dismiss_d2.md", 0.75)],
    "selfsim.md": [("selfsim.md", 0.80)],
    # Equal-score reciprocal tie, tie_b scanned first: the stored pair must be sorted.
    "tie_b.md": [("tie_a.md", 0.70)],
    "tie_a.md": [("tie_b.md", 0.70)],
}

TARGETS = list(SIMILAR.keys())


def _similar_fn(rel_path: str, k: int) -> list[tuple[str, float]]:
    return SIMILAR.get(rel_path, [])[:k]


def _sig(a: str, b: str) -> str:
    return "weaklink|" + "|".join(sorted([a, b]))


def _build_graph():
    graph = graphmark.build(FIXTURE_VAULT)
    # graphmark.build drops self-links (v0.10.0 graph.py), so the self-loop that makes
    # hubn.md a hub is injected here, in memory, after the build.
    graph.out_links["hubn.md"].add("hubn.md")
    graph.back_links["hubn.md"].add("hubn.md")
    return graph


DISMISSED = frozenset({_sig("dismiss_d1.md", "dismiss_d2.md")})


def _call_both():
    graph = _build_graph()
    rank_pairs_result = gaps.rank_pairs(
        graph,
        _similar_fn,
        threshold=THRESHOLD,
        max_score=MAX_SCORE,
        k=K,
        hub_degree=HUB_DEGREE,
        dismissed=DISMISSED,
        targets=TARGETS,
    )

    graph_for_oracle = _build_graph()
    oracle_result = graphmark.metrics.gaps(
        graph_for_oracle,
        _similar_fn,
        threshold=THRESHOLD,
        max_score=MAX_SCORE,
        k=K,
        hub_degree=HUB_DEGREE,
        dismissed=DISMISSED,
        targets=TARGETS,
    )
    return rank_pairs_result, oracle_result, graph_for_oracle


def test_rank_pairs_matches_graphmark_gaps_parity() -> None:
    rank_pairs_result, oracle_result, _ = _call_both()
    expected = [(d["a"], d["b"], d["score"]) for d in oracle_result]
    assert rank_pairs_result == expected


def test_degrees_matches_undirected_degree_for_every_node() -> None:
    graph = _build_graph()
    degrees = gaps._degrees(graph)
    undirected = graphmark.metrics._undirected(graph)
    for node in graph.nodes:
        assert degrees[node] == undirected.degree(node)


def test_hubn_degree_is_neighbors_other_than_itself_plus_two() -> None:
    graph = _build_graph()
    degrees = gaps._degrees(graph)
    real_neighbors = {
        n
        for n in (graph.out_links.get("hubn.md", set()) | graph.back_links.get("hubn.md", set()))
        if n != "hubn.md"
    }
    assert degrees["hubn.md"] == len(real_neighbors) + 2
    assert gaps._degrees(graph)["hubn.md"] == 2


def test_band_edges_inclusive_and_exclusive() -> None:
    result, _, _ = _call_both()
    pairs = {(a, b) for a, b, _ in result}
    assert ("lo.md", "lo_partner.md") in pairs
    assert ("hi.md", "hi_partner.md") in pairs
    assert ("below.md", "below_partner.md") not in pairs
    assert ("above.md", "above_partner.md") not in pairs


def test_linked_pair_absent_from_both_endpoints() -> None:
    result, _, _ = _call_both()
    pairs = {frozenset((a, b)) for a, b, _ in result}
    assert frozenset({"linkA.md", "linkB.md"}) not in pairs


def test_dismissed_pair_absent() -> None:
    result, _, _ = _call_both()
    pairs = {frozenset((a, b)) for a, b, _ in result}
    assert frozenset({"dismiss_d1.md", "dismiss_d2.md"}) not in pairs


def test_duplicate_pair_appears_once_at_higher_score() -> None:
    result, _, _ = _call_both()
    dup_key = frozenset({"dup_p.md", "dup_q.md"})
    dup_entries = [item for item in result if frozenset((item[0], item[1])) == dup_key]
    assert len(dup_entries) == 1
    assert dup_entries[0][2] == 0.75


def test_hub_pair_ranks_after_lower_scoring_nonhub_pair() -> None:
    result, _, _ = _call_both()
    positions = {frozenset((a, b)): i for i, (a, b, _) in enumerate(result)}
    hub_pos = positions[frozenset({"hubn.md", "hubpartner.md"})]
    nonhub_pos = positions[frozenset({"nonhub_x.md", "nonhub_y.md"})]
    hub_a, hub_b, hub_score = result[hub_pos]
    assert "hubn.md" in (hub_a, hub_b)
    assert hub_score == 0.85
    assert hub_pos == len(result) - 1
    assert hub_pos > nonhub_pos


def test_cross_folder_ranks_before_same_folder_at_equal_score() -> None:
    result, _, _ = _call_both()
    positions = {frozenset((a, b)): i for i, (a, b, _) in enumerate(result)}
    cross_pos = positions[frozenset({"same/three.md", "other/four.md"})]
    same_pos = positions[frozenset({"same/one.md", "same/two.md"})]
    assert cross_pos < same_pos


def test_selfsim_note_never_pairs_with_itself() -> None:
    result, _, _ = _call_both()
    assert not any(a == "selfsim.md" and b == "selfsim.md" for a, b, _ in result)
    assert not any("selfsim.md" in (a, b) for a, b, _ in result)


def test_rank_pairs_signature_has_no_defaults_and_no_extra_params() -> None:
    sig = inspect.signature(gaps.rank_pairs)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == [
        "graph",
        "similar_fn",
        "threshold",
        "max_score",
        "k",
        "hub_degree",
        "dismissed",
        "targets",
    ]
    for name in ("threshold", "max_score", "k", "hub_degree", "dismissed", "targets"):
        p = sig.parameters[name]
        assert p.kind == inspect.Parameter.KEYWORD_ONLY
        assert p.default is inspect.Parameter.empty


def test_docstring_has_no_transient_prefix_and_lists_differences() -> None:
    doc = gaps.__doc__ or ""
    assert "transient-prefix" not in doc
    assert re.search(r"(?m)^1\. No ``sig`` in the output", doc)
    assert re.search(r"(?m)^2\. No path-prefix exclusion", doc)


_BANNED_NAMES = {"networkx", "_undirected", "metrics", "dismiss", "weaklink_sig"}


def _scan_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("graphmark") or alias.name.startswith("networkx"):
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if (
                mod == "graphmark"
                or (
                    mod.startswith("graphmark.")
                    and mod not in ("graphmark.graph", "graphmark.interfaces")
                )
                or mod.startswith("networkx")
            ):
                violations.append(f"from {mod} import ...")
        elif isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            violations.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in _BANNED_NAMES:
            violations.append(f"attribute {node.attr}")
    return violations


def test_gaps_py_source_has_no_disallowed_graphmark_or_networkx_references() -> None:
    # The ranking core stays under the full ban.
    for fn in (gaps.rank_pairs, gaps._degrees):
        assert _scan_violations(textwrap.dedent(inspect.getsource(fn))) == []
    # The module as a whole gets exactly the two allowances `gaps()` needs.
    source = Path(gaps.__file__).read_text()
    assert set(_scan_violations(source)) <= {"import graphmark", "name dismiss"}


def test_scan_violations_catches_bad_import() -> None:
    assert _scan_violations("from graphmark import gaps\n") != []


# --- gaps(): the public entry point (the-vault#143 d2, ragmark#149) ----------------------

SimilarFn = Callable[..., list[tuple[str, float]]]

_DEFAULT_STORE = ".claude/data/connect-dismissed.json"


def _note_text(rel: str) -> str:
    return f"# {rel}\n\nBody of {rel}.\n"


def _make_vault(
    tmp_path: Path,
    notes: list[str],
    *,
    context: str | None = None,
    excluded_dirs: frozenset[str] = frozenset(),
    with_index: bool = True,
) -> RagmarkConfig:
    """A throwaway vault under *tmp_path*, an index dir beside it, and its config.

    The index files are empty placeholders: gaps() checks existence only, and every test
    stubs ``search.similar_notes`` (no embedding model is ever involved).
    """
    vault = tmp_path / "vault"
    for rel in notes:
        path = vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_note_text(rel), encoding="utf-8")
    vault.mkdir(exist_ok=True)
    if context is not None:
        (vault / CONTEXT_FILE).write_text(context + "\n", encoding="utf-8")
    index_dir = tmp_path / "index"
    if with_index:
        index_dir.mkdir()
        (index_dir / "ragmark.db").write_bytes(b"")
        (index_dir / "vectors.npy").write_bytes(b"")
    config = RagmarkConfig.for_vault(vault, index_dir=index_dir)
    return dataclasses.replace(config, excluded_dirs=excluded_dirs)


def _stub_similar(
    monkeypatch: pytest.MonkeyPatch,
    table: dict[str, list[tuple[str, float]]],
    *,
    resolve: bool = False,
    ks: list[int] | None = None,
) -> None:
    """Replace ``search.similar_notes`` (the module attribute) with a table lookup.

    ``resolve=True`` mimics the real function's first act: gating the source note through
    ``gate.resolve_note``, which raises ``VaultAccessError`` for a refused target.
    """

    def fake(
        note_path: str, k: int = 8, *, config: RagmarkConfig, store: object
    ) -> list[tuple[str, float]]:
        if ks is not None:
            ks.append(k)
        if resolve:
            gate.resolve_note(note_path, config)
        return list(table.get(note_path, []))[:k]

    monkeypatch.setattr(search, "similar_notes", fake)


def _pairs(result: list[tuple[str, str, float]]) -> set[frozenset[str]]:
    return {frozenset((a, b)) for a, b, _ in result}


def _pair(a: str, b: str) -> frozenset[str]:
    return frozenset((a, b))


def _both_ways(a: str, b: str, score: float) -> dict[str, list[tuple[str, float]]]:
    return {a: [(b, score)], b: [(a, score)]}


def test_gaps_returns_ranked_visible_pairs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"])
    _stub_similar(monkeypatch, _both_ways("brain/a.md", "brain/b.md", 0.81234567))
    assert gaps.gaps(config=config) == [("brain/a.md", "brain/b.md", 0.8123)]


@pytest.mark.gating
def test_gaps_returns_only_context_visible_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = [
        "work/a.md",
        "work/b.md",
        "work/c.md",
        "work/d.md",
        "work/v1.md",
        "work/v2.md",
        "work/x.md",
        "work/y.md",
        "personal/p.md",
    ]
    config = _make_vault(tmp_path, notes, context="work")
    root = config.vault_root
    # Visible, in-band, unlinked, undismissed pair: must survive a hidden dismissal record.
    # personal/p.md is the most similar candidate of work/c.md AND a key of its own with
    # an in-band visible candidate (so dropping the targets filter makes it a ranked target).
    # The stub never calls gate.resolve_note, so a refusal cannot mask a missing filter.
    table = {
        "work/a.md": [("work/b.md", 0.8)],
        "work/c.md": [("personal/p.md", 0.9), ("work/d.md", 0.7)],
        "personal/p.md": [("work/d.md", 0.8)],
        "work/v1.md": [("work/v2.md", 0.75)],
    }
    _stub_similar(monkeypatch, table)

    # Two dismissals against the hidden note (once as `a`, once as `b`), one visible pair.
    dismiss.record_dismissal(root, "personal/p.md", "work/x.md")
    dismiss.record_dismissal(root, "work/y.md", "personal/p.md")
    dismiss.record_dismissal(root, "work/v1.md", "work/v2.md")

    hashed: list[Path] = []
    real_hash = dismiss.content_hash

    def spy(path: Path) -> str:
        hashed.append(path)
        return real_hash(path)

    monkeypatch.setattr(dismiss, "content_hash", spy)
    work_result = gaps.gaps(config=config)
    monkeypatch.setattr(dismiss, "content_hash", real_hash)

    work_pairs = _pairs(work_result)
    assert not any("personal/p.md" in pair for pair in work_pairs)
    assert _pair("work/a.md", "work/b.md") in work_pairs
    assert _pair("work/c.md", "work/d.md") in work_pairs
    assert _pair("work/v1.md", "work/v2.md") not in work_pairs  # dismissed, visible

    hashed_rels = {Path(p).relative_to(root).as_posix() for p in hashed}
    assert "personal/p.md" not in hashed_rels
    assert {"work/v1.md", "work/v2.md"} <= hashed_rels  # the spy does fire

    # Positive control: under the personal context the hidden note is visible.
    (root / CONTEXT_FILE).write_text("personal\n", encoding="utf-8")
    personal_pairs = _pairs(gaps.gaps(config=config))
    assert _pair("work/c.md", "personal/p.md") in personal_pairs
    assert _pair("personal/p.md", "work/d.md") in personal_pairs


def test_default_dismissal_store_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md", "brain/c.md", "brain/d.md"])
    dismiss.record_dismissal(config.vault_root, "brain/a.md", "brain/b.md")
    assert (config.vault_root / _DEFAULT_STORE).is_file()
    table = {
        **_both_ways("brain/a.md", "brain/b.md", 0.8),
        **_both_ways("brain/c.md", "brain/d.md", 0.8),
    }
    _stub_similar(monkeypatch, table)
    pairs = _pairs(gaps.gaps(config=config))
    assert pairs == {_pair("brain/c.md", "brain/d.md")}


def test_explicit_absolute_dismissal_store_outside_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md", "brain/c.md", "brain/d.md"])
    store = tmp_path / "outside" / "d.json"
    dismiss.record_dismissal(config.vault_root, "brain/a.md", "brain/b.md", path=str(store))
    assert store.is_file()
    assert not (config.vault_root / _DEFAULT_STORE).exists()
    table = {
        **_both_ways("brain/a.md", "brain/b.md", 0.8),
        **_both_ways("brain/c.md", "brain/d.md", 0.8),
    }
    _stub_similar(monkeypatch, table)
    pairs = _pairs(gaps.gaps(config=config, dismissal_store=store))
    assert pairs == {_pair("brain/c.md", "brain/d.md")}


def test_explicit_relative_dismissal_store_resolves_against_vault_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md", "brain/c.md", "brain/d.md"])
    relative = Path("custom/d.json")
    dismiss.record_dismissal(config.vault_root, "brain/a.md", "brain/b.md", path=str(relative))
    assert (config.vault_root / relative).is_file()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    table = {
        **_both_ways("brain/a.md", "brain/b.md", 0.8),
        **_both_ways("brain/c.md", "brain/d.md", 0.8),
    }
    _stub_similar(monkeypatch, table)
    pairs = _pairs(gaps.gaps(config=config, dismissal_store=relative))
    assert pairs == {_pair("brain/c.md", "brain/d.md")}


def _snapshot(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def _stub_must_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_run(*args: object, **kwargs: object) -> list:
        raise AssertionError("search ran before the index check")

    monkeypatch.setattr(search, "similar_notes", must_not_run)


def test_missing_index_dir_raises_and_is_not_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"], with_index=False)
    _stub_must_not_run(monkeypatch)
    with pytest.raises(FileNotFoundError) as excinfo:
        gaps.gaps(config=config)
    assert str(config.index_dir) in str(excinfo.value)
    assert "run `ragmark index`" in str(excinfo.value)
    assert not config.index_dir.exists()


def test_index_with_only_vectors_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"])
    (config.index_dir / "ragmark.db").unlink()
    before = _snapshot(config.index_dir)
    _stub_must_not_run(monkeypatch)
    with pytest.raises(FileNotFoundError) as excinfo:
        gaps.gaps(config=config)
    assert str(config.index_dir) in str(excinfo.value)
    assert "run `ragmark index`" in str(excinfo.value)
    assert _snapshot(config.index_dir) == before == ["vectors.npy"]


def test_index_with_only_db_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"])
    (config.index_dir / "vectors.npy").unlink()
    before = _snapshot(config.index_dir)
    _stub_must_not_run(monkeypatch)
    with pytest.raises(FileNotFoundError) as excinfo:
        gaps.gaps(config=config)
    assert str(config.index_dir) in str(excinfo.value)
    assert "run `ragmark index`" in str(excinfo.value)
    assert _snapshot(config.index_dir) == before == ["ragmark.db"]


def test_target_refused_by_the_gate_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_vault(
        tmp_path,
        [".claude/docs/x.md", "archive/y.md", "brain/a.md", "brain/b.md"],
        excluded_dirs=frozenset({"archive"}),
    )
    # The refused notes are targets only, never another note's candidate.
    table = {
        ".claude/docs/x.md": [("brain/a.md", 0.8)],
        "archive/y.md": [("brain/b.md", 0.8)],
        **_both_ways("brain/a.md", "brain/b.md", 0.75),
    }
    _stub_similar(monkeypatch, table, resolve=True)
    with pytest.raises(gate.VaultAccessError):  # the stub does refuse them, as the real one does
        search.similar_notes(".claude/docs/x.md", 8, config=config, store=None)  # type: ignore[call-arg]
    result = gaps.gaps(config=config)
    assert _pairs(result) == {_pair("brain/a.md", "brain/b.md")}
    assert not any(".claude/docs/x.md" in (a, b) or "archive/y.md" in (a, b) for a, b, _ in result)


@pytest.mark.parametrize("edited", ["a", "b"])
def test_edited_note_makes_a_dismissed_pair_reappear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, edited: str
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"])
    dismiss.record_dismissal(config.vault_root, "brain/a.md", "brain/b.md")
    _stub_similar(monkeypatch, _both_ways("brain/a.md", "brain/b.md", 0.8))
    assert gaps.gaps(config=config) == []  # both unedited: dismissal active
    victim = config.vault_root / f"brain/{edited}.md"
    victim.write_text(victim.read_text() + "\nEdited after the dismissal.\n", encoding="utf-8")
    assert _pairs(gaps.gaps(config=config)) == {_pair("brain/a.md", "brain/b.md")}


def test_arguments_are_forwarded_to_rank_pairs_and_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"])
    ks: list[int] = []
    _stub_similar(monkeypatch, {}, ks=ks)
    seen: list[dict[str, object]] = []

    def recorder(graph: object, similar_fn: SimilarFn, **kwargs: object) -> list:
        kwargs["_targets_first"] = kwargs["targets"][0]  # type: ignore[index]
        seen.append(kwargs)
        similar_fn(kwargs["_targets_first"], kwargs["k"])
        return []

    monkeypatch.setattr(gaps, "rank_pairs", recorder)
    result = gaps.gaps(config=config, threshold=0.7, max_score=0.9, k=3, hub_degree=2)
    assert result == []
    assert len(seen) == 1
    kwargs = seen[0]
    assert kwargs["threshold"] == 0.7
    assert kwargs["max_score"] == 0.9
    assert kwargs["k"] == 3
    assert kwargs["hub_degree"] == 2
    assert ks == [3]


@pytest.mark.parametrize("error_type", [RuntimeError, OSError, KeyError, ValueError])
def test_a_search_error_that_is_not_a_gate_refusal_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"])

    def boom(note_path: str, k: int = 8, *, config: RagmarkConfig, store: object) -> list:
        raise error_type("index exploded")

    monkeypatch.setattr(search, "similar_notes", boom)
    with pytest.raises(error_type, match="index exploded"):
        gaps.gaps(config=config)


def test_graph_is_built_once_from_the_vault_root_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"])
    _stub_similar(monkeypatch, _both_ways("brain/a.md", "brain/b.md", 0.8))
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    real_build = graphmark.build

    def spy(*args: object, **kwargs: object):
        calls.append((args, kwargs))
        return real_build(*args, **kwargs)

    monkeypatch.setattr(graphmark, "build", spy)
    gaps.gaps(config=config)
    assert calls == [((config.vault_root,), {})]


@pytest.mark.parametrize("deleted", ["a", "b"])
def test_dismissal_of_a_deleted_note_is_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deleted: str
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md", "brain/c.md"])
    dismiss.record_dismissal(config.vault_root, "brain/a.md", "brain/b.md")
    (config.vault_root / f"brain/{deleted}.md").unlink()
    survivor = "brain/b.md" if deleted == "a" else "brain/a.md"
    _stub_similar(monkeypatch, _both_ways(survivor, "brain/c.md", 0.8))
    assert _pairs(gaps.gaps(config=config)) == {_pair(survivor, "brain/c.md")}


def test_malformed_dismissal_record_is_skipped_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # graphmark v0.10.0 skips a malformed record instead of raising KeyError.
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"])
    store = config.vault_root / _DEFAULT_STORE
    store.parent.mkdir(parents=True)
    sig = "weaklink|brain/a.md|brain/b.md"
    store.write_text(json.dumps({sig: {"a": "brain/a.md", "b": "brain/b.md"}, "junk": 3}))
    _stub_similar(monkeypatch, _both_ways("brain/a.md", "brain/b.md", 0.8))
    assert _pairs(gaps.gaps(config=config)) == {_pair("brain/a.md", "brain/b.md")}


def test_out_of_vault_dismissal_record_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md"])
    outside = tmp_path / "x.md"  # beside the vault root, not under it; exists and is a file
    outside.write_text("outside", encoding="utf-8")
    store = config.vault_root / _DEFAULT_STORE
    store.parent.mkdir(parents=True)
    store.write_text(
        json.dumps(
            {
                "weaklink|brain/a.md|brain/b.md": {
                    "a": "../x.md",
                    "b": "brain/b.md",
                    "a_hash": dismiss.content_hash(outside),
                    "b_hash": dismiss.content_hash(config.vault_root / "brain/b.md"),
                }
            }
        )
    )
    _stub_similar(monkeypatch, _both_ways("brain/a.md", "brain/b.md", 0.8))
    assert _pairs(gaps.gaps(config=config)) == {_pair("brain/a.md", "brain/b.md")}


def test_directory_dismissal_record_is_skipped_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _make_vault(tmp_path, ["brain/a.md", "brain/b.md", "brain/sub/c.md"])
    store = config.vault_root / _DEFAULT_STORE
    store.parent.mkdir(parents=True)
    store.write_text(
        json.dumps(
            {
                "weaklink|brain/a.md|brain/b.md": {
                    "a": "brain/sub",
                    "b": "brain/b.md",
                    "a_hash": "0" * 40,
                    "b_hash": dismiss.content_hash(config.vault_root / "brain/b.md"),
                }
            }
        )
    )
    _stub_similar(monkeypatch, _both_ways("brain/a.md", "brain/b.md", 0.8))
    assert _pairs(gaps.gaps(config=config)) == {_pair("brain/a.md", "brain/b.md")}


def test_sig_is_identical_to_dismiss_weaklink_sig() -> None:
    for a, b in (("a.md", "b.md"), ("z/y.md", "a.md"), ("x.md", "x.md")):
        assert gaps._sig(a, b) == dismiss.weaklink_sig(a, b)


def test_two_root_level_notes_are_same_folder_and_equal_score_pair_is_sorted() -> None:
    sims = {
        "s.md": [("r.md", 0.8)],
        "r.md": [("s.md", 0.8)],
        "g/x.md": [("h/y.md", 0.65)],
        "h/y.md": [("g/x.md", 0.65)],
    }

    def similar(rel: str, k: int) -> list[tuple[str, float]]:
        return sims.get(rel, [])

    graph = graphmark.build(FIXTURE_VAULT)
    graph.nodes.clear()
    graph.out_links.clear()
    graph.back_links.clear()
    result = gaps.rank_pairs(
        graph,
        similar,
        threshold=0.6,
        max_score=0.92,
        k=8,
        hub_degree=40,
        dismissed=set(),
        targets=["s.md", "r.md", "g/x.md", "h/y.md"],
    )
    # Two root-level notes share the "" top folder (graphmark v0.10.0), so that pair is
    # same-folder and ranks after the lower-scoring cross-folder pair; the equal-score
    # pair is stored sorted whichever endpoint was scanned first.
    assert [(a, b) for a, b, _ in result] == [("g/x.md", "h/y.md"), ("r.md", "s.md")]


def test_gaps_py_imports_collaborators_only_as_module_attributes() -> None:
    tree = ast.parse(Path(gaps.__file__).read_text())
    from_ragmark: set[str] = set()
    forbidden = {"ragmark.embed", "ragmark.index", "ragmark.gate", "ragmark.search"}
    forbidden |= {"ragmark.dismiss"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {alias.name for alias in node.names} & forbidden
        elif isinstance(node, ast.ImportFrom):
            assert node.module not in forbidden
            if node.module == "ragmark":
                from_ragmark |= {alias.name for alias in node.names}
    assert {"dismiss", "gate", "search"} <= from_ragmark
    assert not from_ragmark & {"embed", "index"}


def test_module_docstring_lists_context_gating_as_difference_three() -> None:
    doc = gaps.__doc__ or ""
    assert "3. " in doc
    assert "context gating" in doc.lower()
    assert "A later slice appends" not in doc
