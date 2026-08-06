"""CLI regression coverage for the documented refusal paths (issue #6).

Pins two exit-code contracts declared in `cli.py`'s docstring and error
boundary: no-vault-given exits 2 with a stderr message, and an unimplemented
engine seam's `NotImplementedError` becomes exit 2, never a raw traceback.
Also pins the gate's `VaultAccessError` -> exit 1 path and the parser's
subcommand/argument surface.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pytest

from ragmark import search
from ragmark.cli import VAULT_ENV, _build_parser, _json_dump, main
from ragmark.embed import Embedder
from ragmark.golden import GoldenQuery, GoldenReport, GoldenRow
from ragmark.index import RefreshReport
from ragmark.model import (
    ActivityEntry,
    ModelIdentity,
    Neighbor,
    Neighborhood,
    SearchHit,
)


def test_no_vault_exits_2_with_message(monkeypatch, capsys) -> None:
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["ragmark", "search", "q"])

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"error: no vault given (use --vault or ${VAULT_ENV})" in captured.err


def test_not_implemented_seam_exits_2_with_message(monkeypatch, capsys, make_vault) -> None:
    """The CLI's error boundary, not the search seam.

    `search` is implemented now, so the stub is injected here: this test is
    about `main()` turning a seam's `NotImplementedError` into exit 2 with a
    message instead of a traceback, and it must keep testing exactly that as
    the remaining seams land.
    """

    def unimplemented_seam(*args, **kwargs):
        raise NotImplementedError("build slice: a seam not yet landed")

    config = make_vault("personal")
    monkeypatch.setattr(search, "search", unimplemented_seam)
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["ragmark", "--vault", str(config.vault_root), "search", "q"])

    exit_code = main()

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "not implemented in the seed (" in captured.err
    assert "Traceback" not in captured.err


def test_read_missing_note_exits_1_with_gate_message(monkeypatch, capsys, make_vault) -> None:
    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ragmark", "--vault", str(config.vault_root), "read", "brain/never-written.md"],
    )

    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "path is not available: brain/never-written.md" in captured.err
    assert "Traceback" not in captured.err


def test_parser_exposes_all_subcommands() -> None:
    parser = _build_parser()
    sub_actions = [
        action
        for action in parser._subparsers._group_actions  # type: ignore[union-attr]
        if hasattr(action, "choices")
    ]
    (subparsers_action,) = sub_actions
    assert set(subparsers_action.choices) == {
        "search",
        "read",
        "neighbors",
        "recent",
        "golden",
        "index",
        "gaps",
        "mcp",
    }


def test_search_parser_arguments() -> None:
    parser = _build_parser()
    args = parser.parse_args(["search", "hello"])
    assert args.query == "hello"
    assert args.k == search.DEFAULT_RESULTS


def test_read_parser_arguments() -> None:
    parser = _build_parser()
    args = parser.parse_args(["read", "a/b.md"])
    assert args.path == "a/b.md"


def test_neighbors_parser_arguments() -> None:
    from ragmark import neighbors

    parser = _build_parser()
    args = parser.parse_args(["neighbors", "a.md"])
    assert args.path == "a.md"
    assert args.depth == neighbors.DEFAULT_DEPTH
    assert args.budget == neighbors.DEFAULT_TOKEN_BUDGET


def test_recent_parser_arguments() -> None:
    from ragmark import activity

    parser = _build_parser()
    args = parser.parse_args(["recent"])
    assert args.days == activity.DEFAULT_DAYS
    assert args.limit == activity.DEFAULT_LIMIT


def test_golden_parser_arguments() -> None:
    from pathlib import Path

    parser = _build_parser()
    args = parser.parse_args(["golden", "--file", "golden.toml"])
    assert args.file == Path("golden.toml")
    assert args.min_recall is None


def test_index_parser_arguments() -> None:
    parser = _build_parser()
    args = parser.parse_args(["index"])
    assert args.force is False
    args_forced = parser.parse_args(["index", "--force"])
    assert args_forced.force is True


def test_gaps_parser_arguments() -> None:
    from ragmark import gaps

    parser = _build_parser()
    args = parser.parse_args(["gaps"])
    assert args.threshold == gaps.GAPS_DEFAULT_THRESHOLD


def test_mcp_parser_arguments() -> None:
    parser = _build_parser()
    args = parser.parse_args(["mcp"])
    assert args.command == "mcp"


_STUB_DIM = 4


class _StubEmbedder(Embedder):
    """Model-free ruler so the `index` verb runs on a leg with no warm cache."""

    def identity(self) -> ModelIdentity:
        return ModelIdentity(name="stub", dim=_STUB_DIM, version="1")

    def embed(self, texts):
        return np.array(
            [[float(len(text) % 7) for _ in range(_STUB_DIM)] for text in texts],
            dtype=np.float32,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


def test_index_verb_runs_and_prints_a_json_report(monkeypatch, capsys, make_vault) -> None:
    """The `index` verb must execute end to end, not merely parse.

    Every result type is a `slots=True` dataclass, which has no instance
    `__dict__`; serializing via `__dict__` raised `AttributeError` past the
    error boundary as a raw traceback. Parser-only coverage never caught it.
    """
    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)
    monkeypatch.setattr(sys, "argv", ["ragmark", "--vault", str(config.vault_root), "index"])

    exit_code = main()

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert exit_code == 0

    report = json.loads(captured.out)
    assert set(report) == {"added", "updated", "removed", "unchanged", "defects"}
    assert report["added"] > 0
    assert report["defects"] == []


@pytest.mark.parametrize(
    "result",
    [
        RefreshReport(added=1, updated=0, removed=0, unchanged=2, defects=("bad.md",)),
        SearchHit(chunk_id="a.md#0", note_path="a.md", heading=None, score=1.0, snippet="x"),
        Neighborhood(
            origin="a.md",
            context="personal",
            neighbors=(
                Neighbor(
                    note_path="b.md",
                    depth=1,
                    via="a.md",
                    direction="out",
                    tokens=3,
                    included=True,
                    content="body",
                ),
            ),
        ),
        ActivityEntry(note_path="a.md", modified="2026-08-05", first_line="# A"),
        GoldenReport(
            rows=(
                GoldenRow(
                    query=GoldenQuery(text="q", expect=("a.md",), k=8),
                    recall=1.0,
                    found=("a.md",),
                    missed=(),
                ),
            ),
            mean_recall=1.0,
        ),
    ],
    ids=["refresh_report", "search_hit", "neighborhood", "activity_entry", "golden_report"],
)
def test_json_dump_handles_every_slots_result_type(result) -> None:
    """One helper serializes all four verbs, so none can regress alone.

    `Neighborhood` also pins the nested case: its `neighbors` tuple must
    recurse into plain dicts rather than stringifying dataclass reprs.
    """
    payload = json.loads(_json_dump(result))

    assert isinstance(payload, dict)
    if isinstance(result, Neighborhood):
        assert payload["neighbors"][0]["note_path"] == "b.md"
        assert payload["neighbors"][0]["included"] is True
    if isinstance(result, GoldenReport):
        assert payload["rows"][0]["query"]["text"] == "q"
        assert payload["rows"][0]["found"] == ["a.md"]
