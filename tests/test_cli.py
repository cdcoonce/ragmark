"""CLI regression coverage for the documented refusal paths (issue #6).

Pins two exit-code contracts declared in `cli.py`'s docstring and error
boundary: no-vault-given exits 2 with a stderr message, and an unimplemented
engine seam's `NotImplementedError` becomes exit 2, never a raw traceback.
Also pins the gate's `VaultAccessError` -> exit 1 path and the parser's
subcommand/argument surface.
"""

from __future__ import annotations

import sys

import pytest

from ragmark.cli import VAULT_ENV, _build_parser, main


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
    config = make_vault("personal")
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
    from ragmark import search

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
