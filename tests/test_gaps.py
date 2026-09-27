"""Parity tests for ``rank_pairs`` against graphmark v0.9.1's ``metrics.gaps()``.

Fixture vault (`tests/fixtures/gaps/vault/`): band-edge probes (lo/hi exactly on
threshold/max_score, below/above just outside), a real wikilink (linkA -> linkB) for
already-linked filtering in both directions, a hub note (`hubn.md`, made a hub only by an
in-memory self-loop injected after `graphmark.build`), a non-hub pair, same- vs.
cross-folder ties, a duplicate unordered pair at two scores, a dismissed pair, and a note
offered as similar to itself.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import graphmark
import graphmark.metrics
import pytest

from ragmark import gaps
from ragmark.config import RagmarkConfig

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
}

TARGETS = list(SIMILAR.keys())


def _similar_fn(rel_path: str, k: int) -> list[tuple[str, float]]:
    return SIMILAR.get(rel_path, [])[:k]


def _sig(a: str, b: str) -> str:
    return "weaklink|" + "|".join(sorted([a, b]))


def _build_graph():
    graph = graphmark.build(FIXTURE_VAULT)
    # graphmark.build drops self-links (v0.9.1 graph.py:734), so the self-loop that makes
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
    assert hub_pos > nonhub_pos
    assert "hubn.md" in {"hubn.md", "hubpartner.md"}


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


def test_gaps_still_raises_not_implemented(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = RagmarkConfig.for_vault(vault)
    with pytest.raises(NotImplementedError):
        gaps.gaps(config=config)


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
    assert "1." in doc
    assert "2." in doc


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
    source = Path("src/ragmark/gaps.py").read_text()
    assert _scan_violations(source) == []


def test_scan_violations_catches_bad_import() -> None:
    assert _scan_violations("from graphmark import gaps\n") != []
