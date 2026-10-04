"""Standalone absorption checks over temporary external source trees (#173)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_absorption_exit.py"


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    workshop = tmp_path / "workshop"
    vault.mkdir()
    (workshop / "plugins/workbench/machinery/engine").mkdir(parents=True)
    return vault, workshop


def _run(vault: Path, workshop: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--vault-root",
            str(vault),
            "--workshop-root",
            str(workshop),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_external_trees_pass(tmp_path: Path) -> None:
    vault, workshop = _roots(tmp_path)
    (vault / "note.md").write_text("A clean note.\n", encoding="utf-8")

    result = _run(vault, workshop)

    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout
    assert result.stderr == ""


def test_stray_references_in_both_roots_report_each_line(tmp_path: Path) -> None:
    vault, workshop = _roots(tmp_path)
    note = vault / "archive.md"
    source = workshop / "plugins/workbench/machinery/engine/legacy.py"
    note.write_text("Historical note.\nprivate fastembed context\nfastembed again\n")
    source.write_text("# legacy\nimport fastembed\n")

    result = _run(vault, workshop)

    assert result.returncode == 1
    assert f"{note}:2" in result.stdout
    assert f"{note}:3" in result.stdout
    assert f"{source}:2" in result.stdout
    assert "private fastembed context" not in result.stdout
    assert "PASS" not in result.stdout


def test_only_exact_documented_shim_slots_are_allowed(tmp_path: Path) -> None:
    vault, workshop = _roots(tmp_path)
    for root, prefix in (
        (vault, ".claude/scripts"),
        (workshop, "plugins/workbench/machinery/engine"),
    ):
        directory = root / prefix
        directory.mkdir(parents=True, exist_ok=True)
        for name in ("semantic_index.py", "vault_mcp.py"):
            (directory / name).write_text("# fastembed was delegated to ragmark\n")

    allowed = _run(vault, workshop)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr

    near_miss = vault / "semantic_index.py"
    near_miss.write_text("from fastembed import TextEmbedding\n")
    stray = _run(vault, workshop)
    assert stray.returncode == 1
    assert f"{near_miss}:1" in stray.stdout
    assert ".claude/scripts" not in stray.stdout


@pytest.mark.parametrize("bad_root", ["missing-vault", "missing-workshop", "wrong-workshop"])
def test_invalid_roots_cannot_pass(tmp_path: Path, bad_root: str) -> None:
    vault, workshop = _roots(tmp_path)
    if bad_root == "missing-vault":
        vault = tmp_path / "missing-vault"
    elif bad_root == "missing-workshop":
        workshop = tmp_path / "missing-workshop"
    else:
        workshop = tmp_path / "unrelated-directory"
        workshop.mkdir()

    result = _run(vault, workshop)

    assert result.returncode == 2
    assert "error:" in result.stderr
    assert "PASS" not in result.stdout


def test_workshop_root_is_mandatory_even_for_historical_vault(tmp_path: Path) -> None:
    vault, _ = _roots(tmp_path)
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--vault-root", str(vault)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--workshop-root" in result.stderr


def test_roots_must_be_distinct_real_directories(tmp_path: Path) -> None:
    vault, workshop = _roots(tmp_path)
    same = _run(workshop, workshop)
    assert same.returncode == 2
    assert "distinct" in same.stderr

    alias = tmp_path / "vault-alias"
    alias.symlink_to(vault, target_is_directory=True)
    linked = _run(alias, workshop)
    assert linked.returncode == 2
    assert "symlink" in linked.stderr


def test_findings_are_still_reported_when_scan_is_incomplete(tmp_path: Path) -> None:
    vault, workshop = _roots(tmp_path)
    note = vault / "stray.md"
    note.write_text("fastembed\n")
    (workshop / "broken").symlink_to(tmp_path / "missing")

    result = _run(vault, workshop)

    assert result.returncode == 2
    assert f"{note}:1" in result.stdout
    assert "incomplete" in result.stderr
    assert "PASS" not in result.stdout


def test_text_scope_skips_only_git_metadata_and_nul_binary(tmp_path: Path) -> None:
    vault, workshop = _roots(tmp_path)
    (vault / ".git").mkdir()
    (vault / ".git/config").write_text("fastembed\n")
    (workshop / ".git").write_text("gitdir: /path/containing/fastembed\n")
    (vault / "image.bin").write_bytes(b"\x00fastembed\n")
    (vault / "upper.md").write_text("FASTEMBED\n")
    result = _run(vault, workshop)
    assert result.returncode == 0, result.stdout + result.stderr

    hidden = vault / ".history"
    hidden.mkdir()
    historical = hidden / "past.md"
    historical.write_bytes(b"Non-UTF8: \xff\nfastembed archival reference\n")
    result = _run(vault, workshop)
    assert result.returncode == 1
    assert f"{historical}:2" in result.stdout


@pytest.mark.parametrize("entry", ["file", "directory", "shim", "broken"])
def test_symlinks_make_scan_incomplete(tmp_path: Path, entry: str) -> None:
    vault, workshop = _roots(tmp_path)
    target = tmp_path / "outside"
    if entry == "directory":
        target.mkdir()
    elif entry != "broken":
        target.write_text("No references here.\n")
    link = vault / (".claude/scripts/semantic_index.py" if entry == "shim" else "link")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=entry == "directory")

    result = _run(vault, workshop)

    assert result.returncode == 2
    assert str(link) in result.stderr
    assert "symlink" in result.stderr
    assert "PASS" not in result.stdout


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("absorption_checker", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("relative", ["note.md", ".claude/scripts/semantic_index.py"])
def test_unreadable_files_make_scan_incomplete(tmp_path: Path, monkeypatch, checker, relative: str):
    vault, _ = _roots(tmp_path)
    unreadable = vault / relative
    unreadable.parent.mkdir(parents=True, exist_ok=True)
    unreadable.write_text("No references.\n")

    def denied(_path):
        raise PermissionError(13, "Permission denied", str(unreadable))

    monkeypatch.setattr(Path, "read_bytes", denied)
    findings, errors = checker.scan(vault, checker.VAULT_SHIMS)
    assert findings == []
    assert len(errors) == 1
    assert str(unreadable) in errors[0]


def test_unreadable_directory_makes_scan_incomplete(tmp_path: Path, monkeypatch, checker):
    vault, _ = _roots(tmp_path)
    blocked = vault / "blocked"

    def denied_walk(_root, *, onerror):
        onerror(PermissionError(13, "Permission denied", str(blocked)))
        return iter(())

    monkeypatch.setattr(checker.os, "walk", denied_walk)
    findings, errors = checker.scan(vault, checker.VAULT_SHIMS)
    assert findings == []
    assert len(errors) == 1
    assert str(blocked) in errors[0]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX special-file fixture")
def test_special_file_is_rejected_without_reading(tmp_path: Path) -> None:
    vault, workshop = _roots(tmp_path)
    special = vault / "pipe"
    os.mkfifo(special)

    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(SCRIPT),
            "--vault-root",
            str(vault),
            "--workshop-root",
            str(workshop),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=2,
    )
    assert result.returncode == 2
    assert str(special) in result.stderr
    assert "regular file" in result.stderr
