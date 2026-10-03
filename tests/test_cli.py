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
from ragmark.golden import GoldenReport, GoldenRow
from ragmark.index import RefreshReport
from ragmark.model import (
    ActivityEntry,
    ModelIdentity,
    Neighbor,
    Neighborhood,
    SearchHit,
)
from ragmark.store import IndexStore


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


def test_gaps_on_unindexed_vault_exits_1_with_index_message(
    monkeypatch, capsys, make_vault
) -> None:
    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["ragmark", "--vault", str(config.vault_root), "gaps"])

    exit_code = main()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert f"error: no ragmark index at {config.index_dir}" in captured.err
    assert "ragmark index" in captured.err
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


# The fusion mode is selectable from the CLI because the golden oracle is the
# only way to compare the two, and it is driven from here. RRF stays the
# default on every verb — the alternative is opt-in, never implicit.


def test_search_parser_defaults_to_rrf_fusion() -> None:
    parser = _build_parser()
    args = parser.parse_args(["search", "hello"])
    assert args.fusion == search.Fusion.RRF


def test_golden_parser_defaults_to_rrf_fusion() -> None:
    parser = _build_parser()
    args = parser.parse_args(["golden", "--file", "golden.toml"])
    assert args.fusion == search.Fusion.RRF


@pytest.mark.parametrize("verb", [["search", "hello"], ["golden", "--file", "g.toml"]])
def test_fusion_mode_is_selectable(verb: list[str]) -> None:
    parser = _build_parser()
    args = parser.parse_args([*verb, "--fusion", "score"])
    assert args.fusion == search.Fusion.SCORE


def test_golden_passes_the_fusion_mode_into_search(monkeypatch, tmp_path, make_vault) -> None:
    """The flag must reach `search.search`, not just be parsed and dropped.

    Provenance gathering (issue #120) runs after `evaluate`, so this needs a
    real config/store/embedder and an oracle file that exists on disk — bare
    `object()` sentinels don't survive `store.connect()` or `args.file.read_bytes()`.
    """
    import argparse

    from ragmark import cli, golden

    seen: list[object] = []

    def fake_search(query, k, *, config, store, embedder, fusion):
        seen.append(fusion)
        return []

    monkeypatch.setattr(cli.search, "search", fake_search)
    monkeypatch.setattr(
        golden,
        "load_golden",
        lambda path, vault_root=None: [golden.GoldenQuery(text="q", expect=("a.md",), k=8)],
    )

    config = make_vault("personal")
    store = IndexStore(config.index_dir)
    embedder = _StubEmbedder()
    oracle_file = tmp_path / "g.toml"
    oracle_file.write_text("[[query]]\ntext = 'q'\nexpect = ['a.md']\n", encoding="utf-8")
    args = argparse.Namespace(file=oracle_file, min_recall=None, fusion=search.Fusion.SCORE)
    cli._run_golden(args, config, store, embedder)

    assert seen == [search.Fusion.SCORE]


def _regression_block(stdout: str) -> str:
    return stdout.split("regressions vs baseline:", 1)[1]


def test_golden_baseline_prints_only_regressed_queries(
    monkeypatch, capsys, tmp_path, make_vault
) -> None:
    import argparse

    from ragmark import cli, golden

    def fake_search(query, k, *, config, store, embedder, fusion):
        if query == "q1":
            return [type("Hit", (), {"note_path": "a.md"})()]
        return []

    monkeypatch.setattr(cli.search, "search", fake_search)
    monkeypatch.setattr(
        golden,
        "load_golden",
        lambda path, vault_root=None: [
            golden.GoldenQuery(text="q1", expect=("a.md",), k=8),
            golden.GoldenQuery(text="q2", expect=("b.md",), k=8),
        ],
    )

    baseline_report = golden.GoldenReport(
        rows=(
            golden.GoldenRow(query="q1", recall=1.0, found=("a.md",), missed=()),
            golden.GoldenRow(query="q2", recall=1.0, found=("b.md",), missed=()),
        ),
        mean_recall=1.0,
    )
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(_json_dump(baseline_report), encoding="utf-8")

    config = make_vault("personal")
    store = IndexStore(config.index_dir)
    embedder = _StubEmbedder()
    oracle_file = tmp_path / "g.toml"
    oracle_file.write_text(
        "[[query]]\ntext = 'q1'\nexpect = ['a.md']\n\n[[query]]\ntext = 'q2'\nexpect = ['b.md']\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        file=oracle_file,
        min_recall=None,
        fusion=search.Fusion.RRF,
        baseline=baseline_file,
    )

    exit_code = cli._run_golden(args, config, store, embedder)

    captured = capsys.readouterr()
    block = _regression_block(captured.out)
    assert "q2: 1.000 -> 0.000 (-1.000)" in block
    assert "q1" not in block
    assert exit_code == 0


def test_golden_baseline_prints_none_when_nothing_regressed(
    monkeypatch, capsys, tmp_path, make_vault
) -> None:
    import argparse

    from ragmark import cli, golden

    def fake_search(query, k, *, config, store, embedder, fusion):
        return [type("Hit", (), {"note_path": "a.md"})()]

    monkeypatch.setattr(cli.search, "search", fake_search)
    monkeypatch.setattr(
        golden,
        "load_golden",
        lambda path, vault_root=None: [golden.GoldenQuery(text="q1", expect=("a.md",), k=8)],
    )

    baseline_report = golden.GoldenReport(
        rows=(golden.GoldenRow(query="q1", recall=1.0, found=("a.md",), missed=()),),
        mean_recall=1.0,
    )
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(_json_dump(baseline_report), encoding="utf-8")

    config = make_vault("personal")
    store = IndexStore(config.index_dir)
    embedder = _StubEmbedder()
    oracle_file = tmp_path / "g.toml"
    oracle_file.write_text("[[query]]\ntext = 'q1'\nexpect = ['a.md']\n", encoding="utf-8")
    args = argparse.Namespace(
        file=oracle_file,
        min_recall=None,
        fusion=search.Fusion.RRF,
        baseline=baseline_file,
    )

    exit_code = cli._run_golden(args, config, store, embedder)

    captured = capsys.readouterr()
    block = _regression_block(captured.out)
    assert block.strip().splitlines()[0].strip() == "none"
    assert exit_code == 0


def test_golden_baseline_missing_file_returns_error(
    monkeypatch, capsys, tmp_path, make_vault
) -> None:
    import argparse

    from ragmark import cli, golden

    monkeypatch.setattr(
        golden,
        "load_golden",
        lambda path, vault_root=None: [golden.GoldenQuery(text="q1", expect=("a.md",), k=8)],
    )
    monkeypatch.setattr(
        cli.search,
        "search",
        lambda query, k, *, config, store, embedder, fusion: [],
    )

    config = make_vault("personal")
    store = IndexStore(config.index_dir)
    embedder = _StubEmbedder()
    oracle_file = tmp_path / "g.toml"
    oracle_file.write_text("[[query]]\ntext = 'q1'\nexpect = ['a.md']\n", encoding="utf-8")
    missing_baseline = tmp_path / "does-not-exist.json"
    args = argparse.Namespace(
        file=oracle_file,
        min_recall=None,
        fusion=search.Fusion.RRF,
        baseline=missing_baseline,
    )

    exit_code = cli._run_golden(args, config, store, embedder)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "error:" in captured.err
    assert "regressions vs baseline:" not in captured.out


@pytest.mark.parametrize(
    "baseline_content",
    [
        pytest.param("5", id="bare-number"),
        pytest.param("[]", id="empty-list"),
        pytest.param(json.dumps({"mean_recall": 0.5, "rows": [7]}), id="non-dict-row"),
        pytest.param(
            _json_dump(
                GoldenReport(
                    rows=(GoldenRow(query="q1", recall="high", found=(), missed=("a.md",)),),
                    mean_recall=1.0,
                )
            ),
            id="non-numeric-recall",
        ),
    ],
)
def test_golden_baseline_wrong_shape_returns_error_not_traceback(
    monkeypatch, capsys, tmp_path, make_vault, baseline_content
) -> None:
    import argparse

    from ragmark import cli, golden

    monkeypatch.setattr(
        golden,
        "load_golden",
        lambda path, vault_root=None: [golden.GoldenQuery(text="q1", expect=("a.md",), k=8)],
    )
    monkeypatch.setattr(
        cli.search,
        "search",
        lambda query, k, *, config, store, embedder, fusion: [],
    )

    config = make_vault("personal")
    store = IndexStore(config.index_dir)
    embedder = _StubEmbedder()
    oracle_file = tmp_path / "g.toml"
    oracle_file.write_text("[[query]]\ntext = 'q1'\nexpect = ['a.md']\n", encoding="utf-8")
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(baseline_content, encoding="utf-8")
    args = argparse.Namespace(
        file=oracle_file,
        min_recall=None,
        fusion=search.Fusion.RRF,
        baseline=baseline_file,
    )

    exit_code = cli._run_golden(args, config, store, embedder)

    captured = capsys.readouterr()
    assert exit_code == 1
    err_lines = captured.err.splitlines()
    assert len(err_lines) == 1
    assert err_lines[0].startswith("error:")
    assert "regressions vs baseline:" not in captured.out


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


_GOLDEN_ORACLE = (
    "[[query]]\n"
    "text = 'branch protection'\n"
    "expect = ['work/decisions/platform-choice.md']\n"
    "\n"
    "[[query]]\n"
    "text = 'side project notes'\n"
    "expect = ['personal/projects/side-project.md']\n"
)


def test_golden_verb_records_provenance(monkeypatch, capsys, make_vault, tmp_path) -> None:
    """The `golden` verb's saved JSON is attributable to its inputs (issue #120)."""
    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)

    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_GOLDEN_ORACLE, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ragmark",
            "--vault",
            str(config.vault_root),
            "golden",
            "--file",
            str(oracle_file),
            "--fusion",
            "score",
        ],
    )

    exit_code = main()

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert exit_code == 0

    report = json.loads(captured.out)
    provenance = report["provenance"]

    store = IndexStore(config.index_dir)
    conn = store.connect()
    try:
        expected_chunk_count = store.chunk_count(conn)
        expected_note_count = len(store.read_notes(conn))
    finally:
        conn.close()
    assert expected_chunk_count > 0
    assert expected_note_count > 0

    assert provenance["chunk_count"] == expected_chunk_count
    assert provenance["note_count"] == expected_note_count
    assert provenance["query_count"] == 2
    assert provenance["model_name"] == "stub"
    assert provenance["model_dim"] == _STUB_DIM
    assert provenance["model_version"] == "1"
    assert provenance["fusion"] == "score"


def test_golden_reports_no_drift_when_corpus_is_stable(
    monkeypatch, capsys, make_vault, tmp_path
) -> None:
    """A run whose corpus doesn't change mid-loop gets today's payload plus
    the four fingerprint keys, an empty stderr, and exit 0 (issue #121)."""
    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)

    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_GOLDEN_ORACLE, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ragmark", "--vault", str(config.vault_root), "golden", "--file", str(oracle_file)],
    )

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""

    payload = json.loads(captured.out)
    assert set(payload) == {
        "rows",
        "mean_recall",
        "provenance",
        "notes_before",
        "chunks_before",
        "notes_after",
        "chunks_after",
    }
    assert payload["notes_before"] == payload["notes_after"] > 0
    assert payload["chunks_before"] == payload["chunks_after"] > 0


def test_golden_detects_corpus_drift_mid_run(monkeypatch, capsys, make_vault, tmp_path) -> None:
    """A chunk row inserted into the real store between the two fingerprint
    readings is caught, not silently folded into a single measurement
    (issue #121). The insert happens via a patched `search.search` so the
    detection path itself — not just the comparison — is exercised."""
    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)

    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_GOLDEN_ORACLE, encoding="utf-8")

    inserted = False

    def drifting_search(query, k, *, config, store, embedder, fusion):
        nonlocal inserted
        if not inserted:
            inserted = True
            conn = store.connect()
            try:
                conn.execute(
                    "INSERT INTO chunks (chunk_id, note_path, chunk_index, heading, "
                    "parent_ref, text, token_count, vector_row) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("drift-chunk", "drift-note.md", 0, None, None, "drift text", 2, -1),
                )
                conn.commit()
            finally:
                conn.close()
        return []

    monkeypatch.setattr(search, "search", drifting_search)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ragmark", "--vault", str(config.vault_root), "golden", "--file", str(oracle_file)],
    )

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1

    payload = json.loads(captured.out)
    assert payload["notes_before"] == payload["notes_after"]
    assert payload["chunks_after"] == payload["chunks_before"] + 1
    assert str(payload["chunks_before"]) in captured.err
    assert str(payload["chunks_after"]) in captured.err
    assert "notes" in captured.err
    assert "chunks" in captured.err


def test_golden_oracle_sha256_is_stable_and_changes_with_content(
    monkeypatch, capsys, make_vault, tmp_path
) -> None:
    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)

    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_GOLDEN_ORACLE, encoding="utf-8")

    def run_golden() -> dict:
        monkeypatch.setattr(
            sys,
            "argv",
            ["ragmark", "--vault", str(config.vault_root), "golden", "--file", str(oracle_file)],
        )
        main()
        return json.loads(capsys.readouterr().out)

    first = run_golden()
    second = run_golden()
    assert first["provenance"]["oracle_sha256"] == second["provenance"]["oracle_sha256"]

    oracle_file.write_text(_GOLDEN_ORACLE + "\n# a comment appended\n", encoding="utf-8")
    third = run_golden()
    assert third["provenance"]["oracle_sha256"] != first["provenance"]["oracle_sha256"]


def test_golden_provenance_vault_git_state_absent_outside_a_repo(
    monkeypatch, capsys, make_vault, tmp_path
) -> None:
    """`make_vault` copies a fixture into a plain tmp dir, not a git work tree."""
    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)

    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_GOLDEN_ORACLE, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ragmark", "--vault", str(config.vault_root), "golden", "--file", str(oracle_file)],
    )

    exit_code = main()

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["provenance"]["vault_revision"] is None
    assert report["provenance"]["vault_dirty"] is None


def test_golden_provenance_vault_git_state_present_inside_a_repo(
    monkeypatch, capsys, make_vault, tmp_path
) -> None:
    """Explicit committer identity so the commit never depends on ambient git config."""
    import subprocess

    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)

    vault_root = config.vault_root
    (vault_root / ".gitignore").write_text(".ragmark/\n", encoding="utf-8")
    git_commit = [
        "git",
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        "initial",
    ]
    subprocess.run(["git", "init"], cwd=vault_root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=vault_root, check=True, capture_output=True)
    subprocess.run(git_commit, cwd=vault_root, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=vault_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_GOLDEN_ORACLE, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ragmark", "--vault", str(vault_root), "golden", "--file", str(oracle_file)],
    )

    main()
    clean_report = json.loads(capsys.readouterr().out)
    assert clean_report["provenance"]["vault_revision"] == head
    assert clean_report["provenance"]["vault_dirty"] is False

    (vault_root / "work" / "decisions" / "platform-choice.md").write_text(
        "dirtied for the test\n", encoding="utf-8"
    )
    main()
    dirty_report = json.loads(capsys.readouterr().out)
    assert dirty_report["provenance"]["vault_revision"] == head
    assert dirty_report["provenance"]["vault_dirty"] is True


_STALE_GOLDEN_ORACLE = (
    "[[query]]\ntext = 'branch protection'\nexpect = ['work/decisions/renamed-note.md']\n"
)


def test_golden_stale_expect_path_exits_1_before_refresh(
    monkeypatch, capsys, tmp_path, make_vault
) -> None:
    """A stale `expect` path fails loud before any index work (issue #145)."""
    import argparse

    from ragmark import cli, index

    def refresh_must_not_run(*args, **kwargs):
        raise AssertionError("index.refresh must not run when the oracle is stale")

    monkeypatch.setattr(index, "refresh", refresh_must_not_run)

    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)

    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_STALE_GOLDEN_ORACLE, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ragmark", "--vault", str(config.vault_root), "golden", "--file", str(oracle_file)],
    )

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Traceback" not in captured.err
    assert "error: " in captured.err
    assert "query #0" in captured.err
    assert "work/decisions/renamed-note.md" in captured.err

    store = IndexStore(config.index_dir)
    embedder = _StubEmbedder()
    args = argparse.Namespace(
        file=oracle_file,
        min_recall=None,
        fusion=search.Fusion.RRF,
        baseline=None,
    )
    direct_exit_code = cli._run_golden(args, config, store, embedder)
    assert direct_exit_code == 1


def test_golden_missing_vault_root_exits_1_before_refresh(
    monkeypatch, capsys, tmp_path, make_vault
) -> None:
    """`vault_root` is always passed, even when it doesn't exist (issue #145)."""
    import argparse
    from dataclasses import replace

    from ragmark import cli, index

    def refresh_must_not_run(*args, **kwargs):
        raise AssertionError("index.refresh must not run when vault_root is missing")

    monkeypatch.setattr(index, "refresh", refresh_must_not_run)

    config = make_vault("personal")
    missing_root = tmp_path / "no-such-vault"
    config = replace(config, vault_root=missing_root)

    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_GOLDEN_ORACLE, encoding="utf-8")

    store = IndexStore(config.index_dir)
    embedder = _StubEmbedder()
    args = argparse.Namespace(
        file=oracle_file,
        min_recall=None,
        fusion=search.Fusion.RRF,
        baseline=None,
    )

    exit_code = cli._run_golden(args, config, store, embedder)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Traceback" not in captured.err
    assert f"error: vault_root not found: {missing_root}" in captured.err


def test_golden_missing_file_raises_filenotfounderror(monkeypatch, tmp_path, make_vault) -> None:
    from ragmark import index

    def refresh_must_not_run(*args, **kwargs):
        raise AssertionError("index.refresh must not run when the oracle file is missing")

    monkeypatch.setattr(index, "refresh", refresh_must_not_run)

    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)

    missing_file = tmp_path / "does-not-exist.toml"
    monkeypatch.setattr(
        sys,
        "argv",
        ["ragmark", "--vault", str(config.vault_root), "golden", "--file", str(missing_file)],
    )

    with pytest.raises(FileNotFoundError):
        main()


@pytest.mark.parametrize(
    "target",
    ["evaluate", "refresh", "fingerprint"],
)
def test_golden_try_block_wraps_only_load_golden(
    monkeypatch, tmp_path, make_vault, target: str
) -> None:
    """The `try` around `load_golden` must not swallow defects raised later
    in `_run_golden` — only the load itself (issue #145)."""
    import argparse

    from ragmark import cli, golden, index

    if target == "evaluate":
        message = "evaluate defect"

        def raiser(*args, **kwargs):
            raise ValueError(message)

        monkeypatch.setattr(golden, "evaluate", raiser)
    elif target == "refresh":
        message = "refresh defect"

        def raiser(*args, **kwargs):
            raise ValueError(message)

        monkeypatch.setattr(index, "refresh", raiser)
    else:
        message = "fingerprint defect"

        def raiser(*args, **kwargs):
            raise ValueError(message)

        monkeypatch.setattr(cli, "_corpus_fingerprint", raiser)

    config = make_vault("personal")
    store = IndexStore(config.index_dir)
    embedder = _StubEmbedder()
    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_GOLDEN_ORACLE, encoding="utf-8")
    args = argparse.Namespace(
        file=oracle_file,
        min_recall=None,
        fusion=search.Fusion.RRF,
        baseline=None,
    )

    with pytest.raises(ValueError, match=message):
        cli._run_golden(args, config, store, embedder)


def test_main_does_not_map_valueerror_for_search_verb(monkeypatch, make_vault) -> None:
    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)

    def raiser(*args, **kwargs):
        raise ValueError("search defect")

    monkeypatch.setattr(search, "search", raiser)
    monkeypatch.setattr(sys, "argv", ["ragmark", "--vault", str(config.vault_root), "search", "q"])

    with pytest.raises(ValueError, match="search defect"):
        main()


def test_main_does_not_map_valueerror_for_golden_verb(monkeypatch, tmp_path, make_vault) -> None:
    from ragmark import golden

    config = make_vault("personal")
    monkeypatch.delenv(VAULT_ENV, raising=False)
    monkeypatch.setattr("ragmark.cli.FastembedEmbedder", _StubEmbedder)

    def raiser(*args, **kwargs):
        raise ValueError("evaluate defect")

    monkeypatch.setattr(golden, "evaluate", raiser)

    oracle_file = tmp_path / "golden.toml"
    oracle_file.write_text(_GOLDEN_ORACLE, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ragmark", "--vault", str(config.vault_root), "golden", "--file", str(oracle_file)],
    )

    with pytest.raises(ValueError, match="evaluate defect"):
        main()


def test_golden_subparser_adds_no_opt_out_argument() -> None:
    import argparse

    parser = _build_parser()

    args = parser.parse_args(["golden", "--file", "g.toml"])
    assert set(vars(args)) == {
        "vault",
        "config",
        "command",
        "file",
        "min_recall",
        "baseline",
        "fusion",
    }

    subparsers_action = next(
        action
        for action in parser._actions  # type: ignore[union-attr]
        if isinstance(action, argparse._SubParsersAction)
    )
    golden_actions = subparsers_action.choices["golden"]._actions  # type: ignore[union-attr]
    assert [action.dest for action in golden_actions] == [
        "help",
        "file",
        "min_recall",
        "baseline",
        "fusion",
    ]

    assert [action.dest for action in parser._actions] == ["help", "vault", "config", "command"]  # type: ignore[union-attr]


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
                    query="q",
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
        assert payload["rows"][0]["query"] == "q"
        assert isinstance(payload["rows"][0]["query"], str)
        assert payload["rows"][0]["found"] == ["a.md"]
