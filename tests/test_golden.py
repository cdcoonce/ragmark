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
