"""Note-level presentation of supplied, already-gated chunk search results."""

import pytest

from ragmark.compat import note_results
from ragmark.model import SearchHit
from ragmark.search import DEFAULT_RESULTS, MAX_RESULTS


def test_first_ranked_chunk_supplies_each_notes_legacy_fields() -> None:
    hits = (
        SearchHit("notes/z.md#2", "notes/z.md", "Current", 0.032, "Current details"),
        SearchHit("notes/z.md#0", "notes/z.md", None, 0.030, "Description"),
        SearchHit("notes/a.md#1", "notes/a.md", "Next", 0.025, "Next steps"),
    )

    assert note_results(hits) == [
        {"note_path": "notes/z.md", "score": 0.032, "snippet": "Current details"},
        {"note_path": "notes/a.md", "score": 0.025, "snippet": "Next steps"},
    ]


def test_k_counts_distinct_notes_after_deduplication() -> None:
    hits = (
        SearchHit("a.md#0", "a.md", None, 0.032, "First"),
        SearchHit("a.md#1", "a.md", None, 0.031, "Duplicate"),
        SearchHit("b.md#0", "b.md", None, 0.030, "Second"),
        SearchHit("c.md#0", "c.md", None, 0.029, "Third"),
    )

    assert [result["note_path"] for result in note_results(hits, k=2)] == ["a.md", "b.md"]


@pytest.mark.parametrize("k", [0, -1, -100])
def test_nonpositive_k_returns_no_results(k: int) -> None:
    hits = [SearchHit("a.md#0", "a.md", None, 0.032, "First")]

    assert note_results(hits, k=k) == []


def test_oversized_k_uses_the_core_search_cap() -> None:
    hits = [
        SearchHit(f"{i}.md#0", f"{i}.md", None, 1 / (61 + i), f"Snippet {i}")
        for i in range(MAX_RESULTS + 5)
    ]

    results = note_results(hits, k=10_000)

    assert len(results) == MAX_RESULTS
    assert [result["note_path"] for result in results] == [
        hit.note_path for hit in hits[:MAX_RESULTS]
    ]


def test_default_k_matches_core_search_default() -> None:
    hits = [
        SearchHit(f"{i}.md#0", f"{i}.md", None, 1 / (61 + i), f"Snippet {i}")
        for i in range(DEFAULT_RESULTS + 2)
    ]

    assert len(note_results(hits)) == DEFAULT_RESULTS == 8


def test_ties_keep_supplied_order_without_changing_source_hits() -> None:
    hits = [
        SearchHit("z.md#2", "z.md", "First", 0.02, "Ranked first"),
        SearchHit("a.md#0", "a.md", None, 0.02, "Ranked second"),
        SearchHit("z.md#0", "z.md", None, 0.02, "Later chunk"),
    ]
    before = tuple(hits)

    results = note_results(hits)

    assert [result["note_path"] for result in results] == ["z.md", "a.md"]
    assert results[0]["snippet"] == "Ranked first"
    assert tuple(hits) == before
    assert hits[0].chunk_id == "z.md#2"


def test_low_fused_score_and_supplied_snippet_are_preserved() -> None:
    snippet = "Current section — " + "Long supplied chunk text. " * 20
    hit = SearchHit("a.md#3", "a.md", "Current section", 1 / 1_060, snippet)

    assert note_results([hit]) == [{"note_path": "a.md", "score": hit.score, "snippet": snippet}]


def test_fewer_unique_notes_yield_a_short_result() -> None:
    hits = [
        SearchHit("a.md#0", "a.md", None, 0.03, "Only unique note"),
        SearchHit("a.md#1", "a.md", None, 0.02, "Another chunk"),
    ]

    assert note_results(hits, k=8) == [
        {"note_path": "a.md", "score": 0.03, "snippet": "Only unique note"}
    ]


def test_empty_hits_yield_no_results() -> None:
    assert note_results([]) == []


def test_public_status_preserves_read_only_missing_state(tmp_path) -> None:
    from ragmark import compat
    from ragmark.config import RagmarkConfig
    from ragmark.model import ModelIdentity
    from ragmark.store import IndexStore

    config = RagmarkConfig.for_vault(tmp_path)
    result = compat.status(config, IndexStore(config.index_dir), ModelIdentity("stub", 2, "1"))

    assert result["state"] == "missing"
    assert result["ready"] is False
    assert result["index_built_at"] is None
    assert not config.index_dir.exists()
