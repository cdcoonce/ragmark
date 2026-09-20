"""The golden-query harness: format validation and recall math."""

from __future__ import annotations

from pathlib import Path

import pytest

from ragmark import golden

VALID = """
[[query]]
text = "what did we decide about branch protection"
expect = ["reference/git.md", "brain/decisions.md"]

[[query]]
text = "chunking token ceiling"
expect = ["reference/rag.md"]
k = 3
"""


def write_golden(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "golden.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_valid_file_with_default_k(tmp_path: Path) -> None:
    queries = golden.load_golden(write_golden(tmp_path, VALID))
    assert len(queries) == 2
    assert queries[0].k == golden.DEFAULT_K
    assert queries[1].k == 3
    assert queries[0].expect == ("reference/git.md", "brain/decisions.md")


@pytest.mark.parametrize(
    "content",
    [
        "",
        "[[query]]\ntext = ''\nexpect = ['a.md']",
        "[[query]]\ntext = 'q'\nexpect = []",
        "[[query]]\ntext = 'q'\nexpect = ['a.md']\nk = 0",
    ],
)
def test_invalid_files_are_refused(tmp_path: Path, content: str) -> None:
    with pytest.raises((ValueError, FileNotFoundError)):
        golden.load_golden(write_golden(tmp_path, content))


def test_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        golden.load_golden(tmp_path / "absent.toml")


def test_evaluate_scores_recall_at_k(tmp_path: Path) -> None:
    queries = golden.load_golden(write_golden(tmp_path, VALID))

    def search_notes(text: str, k: int) -> list[str]:
        if "branch protection" in text:
            return ["reference/git.md", "reference/unrelated.md"]
        return ["reference/rag.md"]

    report = golden.evaluate(queries, search_notes)

    first, second = report.rows
    assert first.recall == 0.5
    assert first.found == ("reference/git.md",)
    assert first.missed == ("brain/decisions.md",)
    assert second.recall == 1.0
    assert report.mean_recall == 0.75


def test_evaluate_empty_set_is_zero_not_crash() -> None:
    report = golden.evaluate([], lambda text, k: [])
    assert report.rows == ()
    assert report.mean_recall == 0.0


def test_vault_root_refuses_missing_expect_path(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "reference").mkdir(parents=True)
    (vault_root / "reference" / "git.md").write_text("real note", encoding="utf-8")

    content = """
[[query]]
text = "what did we decide about branch protection"
expect = ["reference/git.md", "reference/renamed-away.md"]
"""
    golden_path = write_golden(tmp_path, content)

    with pytest.raises(ValueError, match=r"query #0.*reference/renamed-away\.md"):
        golden.load_golden(golden_path, vault_root=vault_root)


def test_vault_root_accepts_existing_expect_path(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "reference").mkdir(parents=True)
    (vault_root / "reference" / "git.md").write_text("real note", encoding="utf-8")

    content = """
[[query]]
text = "what did we decide about branch protection"
expect = ["reference/git.md"]
"""
    golden_path = write_golden(tmp_path, content)

    queries = golden.load_golden(golden_path, vault_root=vault_root)
    assert queries[0].expect == ("reference/git.md",)


def test_no_vault_root_does_not_check_existence(tmp_path: Path) -> None:
    content = """
[[query]]
text = "what did we decide about branch protection"
expect = ["reference/does-not-exist.md"]
"""
    golden_path = write_golden(tmp_path, content)

    queries = golden.load_golden(golden_path)
    assert queries[0].expect == ("reference/does-not-exist.md",)


def _row(query: str, recall: float) -> golden.GoldenRow:
    return golden.GoldenRow(query=query, recall=recall, found=(), missed=())


def test_diff_reports_pairs_shared_queries_in_baseline_order() -> None:
    baseline = golden.GoldenReport(
        rows=(
            _row("alpha", 0.5),
            _row("bravo", 1.0),
            _row("charlie", 0.25),
            _row("baseline-only", 0.75),
        ),
        mean_recall=0.625,
    )
    current = golden.GoldenReport(
        rows=(
            _row("charlie", 0.0),
            _row("bravo", 1.0),
            _row("alpha", 0.75),
            _row("current-only", 0.5),
        ),
        mean_recall=0.583,
    )

    result = golden.diff_reports(baseline, current)

    assert [r.query for r in result] == ["alpha", "bravo", "charlie"]
    assert result[0] == golden.GoldenRegression(
        query="alpha", baseline_recall=0.5, current_recall=0.75, delta=0.25
    )
    assert result[1] == golden.GoldenRegression(
        query="bravo", baseline_recall=1.0, current_recall=1.0, delta=0.0
    )
    assert result[2] == golden.GoldenRegression(
        query="charlie", baseline_recall=0.25, current_recall=0.0, delta=-0.25
    )
    assert not any(r.query in ("baseline-only", "current-only") for r in result)
