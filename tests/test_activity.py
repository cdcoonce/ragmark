"""git-log-backed recent activity (the-vault#142, issue #10).

Fixture git repos are built at test time in `tmp_path`: commit times are
relative to the wall clock (never absolute calendar dates, which would age
out of the window), created oldest-first so `git log --since` walks them
correctly, with every `GIT_AUTHOR_DATE` fixed 30 days before its
`GIT_COMMITTER_DATE` -- the implementation must key off committer date, not
author date. On-disk mtimes are set in the OPPOSITE order to commit times,
so an mtime-based (or author-date-based) implementation disagrees with the
committer-date-based one. Each repo carries an `origin` remote pointing at a
nonexistent path plus a `remote.origin.uploadpack` sentinel script, so any
accidental `fetch`/`pull`/`ls-remote` is caught by asserting the sentinel is
never created.
"""

from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from ragmark.activity import DEFAULT_DAYS, DEFAULT_LIMIT, recent_activity
from ragmark.config import CONTEXT_FILE, RagmarkConfig

_MODIFIED_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00")


@pytest.fixture(autouse=True)
def _non_utc_timezone():
    original = os.environ.get("TZ")
    os.environ["TZ"] = "America/Phoenix"
    time.tzset()
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def _git(repo_root: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        encoding="utf-8",
        check=True,
        env=env,
    )


def _base_git_env(tmp_path: Path) -> dict[str, str]:
    global_config = tmp_path / "gitconfig"
    if not global_config.exists():
        global_config.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(global_config)
    env["GIT_AUTHOR_NAME"] = "Activity Test"
    env["GIT_AUTHOR_EMAIL"] = "activity-test@example.com"
    env["GIT_COMMITTER_NAME"] = "Activity Test"
    env["GIT_COMMITTER_EMAIL"] = "activity-test@example.com"
    return env


def _setup_repo(tmp_path: Path, dirname: str) -> tuple[Path, dict[str, str], Path]:
    repo_root = tmp_path / dirname
    repo_root.mkdir()
    env = _base_git_env(tmp_path)
    _git(repo_root, "init", "-q", env=env)

    sentinel = tmp_path / f"{dirname}-uploadpack-sentinel"
    script = tmp_path / f"{dirname}-fake-uploadpack.sh"
    script.write_text(f"#!/bin/sh\n: > {sentinel}\n", encoding="utf-8")
    script.chmod(0o755)

    nonexistent_origin = tmp_path / f"{dirname}-nonexistent-origin"
    _git(repo_root, "remote", "add", "origin", str(nonexistent_origin), env=env)
    _git(repo_root, "config", "remote.origin.uploadpack", str(script), env=env)
    return repo_root, env, sentinel


def _commit(repo_root: Path, base_env: dict[str, str], when: datetime, message: str) -> None:
    env = dict(base_env)
    env["GIT_AUTHOR_DATE"] = (when - timedelta(days=30)).astimezone(UTC).isoformat()
    env["GIT_COMMITTER_DATE"] = when.astimezone(UTC).isoformat()
    _git(repo_root, "add", "-A", env=base_env)
    _git(repo_root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message, env=env)


@pytest.fixture
def git_vault(tmp_path: Path):
    repo_root, env, sentinel = _setup_repo(tmp_path, "repo")
    now = datetime.now(UTC)
    note_times: dict[str, datetime] = {}

    def write(rel: str, content: str) -> None:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    write("old8.md", "content old8\n")
    _commit(repo_root, env, now - timedelta(days=8), "old8")
    note_times["old8.md"] = now - timedelta(days=8)

    write("recent6.md", "content recent6\n")
    _commit(repo_root, env, now - timedelta(days=6), "recent6")
    note_times["recent6.md"] = now - timedelta(days=6)

    write("twice.md", "content twice v1\n")
    _commit(repo_root, env, now - timedelta(days=5), "twice v1")
    note_times["twice.md"] = now - timedelta(days=5)

    write("deleted.md", "content deleted\n")
    _commit(repo_root, env, now - timedelta(days=4), "deleted create")
    (repo_root / "deleted.md").unlink()
    _commit(repo_root, env, now - timedelta(days=4) + timedelta(hours=2), "deleted delete")

    write("same-a.md", "content same a\n")
    write("same-b.md", "content same b\n")
    same_time = now - timedelta(days=3)
    _commit(repo_root, env, same_time, "same commit pair")
    note_times["same-a.md"] = same_time
    note_times["same-b.md"] = same_time

    write("twice.md", "content twice v2\n")
    _commit(repo_root, env, now - timedelta(days=2), "twice v2")
    note_times["twice.md"] = now - timedelta(days=2)

    write(".vault-context", "work\n")
    write("notes.txt", "not a note\n")
    write(".claude/x.md", "hidden note\n")
    write("drafts/excluded.md", "excluded note\n")
    nonnote_time = now - timedelta(days=1)
    _commit(repo_root, env, nonnote_time, "non-note files")
    # Not excluded under the default config (empty excluded_dirs): it is a
    # legitimate note candidate there, only filtered by the dedicated test
    # that opts into excluded_dirs={"drafts"}.
    note_times["drafts/excluded.md"] = nonnote_time

    write("malformed.md", "---\nkey: [unterminated\n---\nmalformed body\n")
    malformed_time = now - timedelta(days=1) + timedelta(minutes=1)
    _commit(repo_root, env, malformed_time, "malformed frontmatter")
    note_times["malformed.md"] = malformed_time

    write(
        "firstline.md",
        "---\ndescription: has heading first\n---\n\n# Heading First\nMore text.\n",
    )
    firstline_time = now - timedelta(days=1) + timedelta(minutes=2)
    _commit(repo_root, env, firstline_time, "firstline heading")
    note_times["firstline.md"] = firstline_time

    write("emptybody.md", "---\ndescription: nothing here\n---\n")
    emptybody_time = now - timedelta(days=1) + timedelta(minutes=3)
    _commit(repo_root, env, emptybody_time, "empty body")
    note_times["emptybody.md"] = emptybody_time

    outside_target = tmp_path / "outside-target.md"
    outside_target.write_text("outside content\n", encoding="utf-8")
    os.symlink(str(outside_target), str(repo_root / "symlink.md"))
    symlink_time = now - timedelta(days=1) + timedelta(minutes=4)
    _commit(repo_root, env, symlink_time, "symlink note")
    note_times["symlink.md"] = symlink_time

    write("personal/secret.md", "content personal secret\n")
    personal_time = now - timedelta(days=1) + timedelta(minutes=5)
    _commit(repo_root, env, personal_time, "personal secret")
    note_times["personal/secret.md"] = personal_time

    # Reverse on-disk mtimes relative to commit order: the oldest commit gets
    # the newest mtime and vice versa, so a wrong (mtime-keyed) implementation
    # disagrees with the correct (committer-date-keyed) one.
    ordered = sorted(note_times.items(), key=lambda kv: kv[1])
    reversed_times = [t for _, t in ordered][::-1]
    for (rel, _), mtime_dt in zip(ordered, reversed_times, strict=True):
        ts = mtime_dt.timestamp()
        os.utime(repo_root / rel, (ts, ts), follow_symlinks=False)

    config = RagmarkConfig.for_vault(repo_root)
    yield SimpleNamespace(
        repo_root=repo_root, config=config, sentinel=sentinel, note_times=note_times
    )
    assert not sentinel.exists(), "recent_activity must never contact a remote"


@pytest.fixture
def git_vault_51(tmp_path: Path):
    repo_root, env, sentinel = _setup_repo(tmp_path, "repo51")
    now = datetime.now(UTC)
    bulk_time = now - timedelta(minutes=10)

    for i in range(51):
        (repo_root / f"bulk-{i:03d}.md").write_text(f"bulk note {i}\n", encoding="utf-8")
    _commit(repo_root, env, bulk_time, "bulk notes")

    personal_dir = repo_root / "personal"
    personal_dir.mkdir()
    (personal_dir / "newer.md").write_text("newer personal note\n", encoding="utf-8")
    _commit(repo_root, env, bulk_time + timedelta(seconds=1), "personal newer note")

    (repo_root / CONTEXT_FILE).write_text("work\n", encoding="utf-8")
    config = RagmarkConfig.for_vault(repo_root)
    yield SimpleNamespace(config=config, sentinel=sentinel)
    assert not sentinel.exists(), "recent_activity must never contact a remote"


@pytest.fixture
def git_vault_subdir(tmp_path: Path):
    repo_root, env, sentinel = _setup_repo(tmp_path, "repo-subdir")
    vault_root = repo_root / "vault"
    vault_root.mkdir()
    now = datetime.now(UTC)

    (repo_root / "outside.md").write_text("outside vault content\n", encoding="utf-8")
    _commit(repo_root, env, now - timedelta(days=2), "outside vault note")

    inner_dir = vault_root / "notes"
    inner_dir.mkdir()
    inner_path = inner_dir / "a.md"
    inner_path.write_text("inside vault content\n", encoding="utf-8")
    inner_time = now - timedelta(days=1)
    _commit(repo_root, env, inner_time, "inside vault note")

    wrong_mtime = (inner_time - timedelta(days=2)).timestamp()
    os.utime(inner_path, (wrong_mtime, wrong_mtime))

    (vault_root / CONTEXT_FILE).write_text("work\n", encoding="utf-8")
    config = RagmarkConfig.for_vault(vault_root)
    yield SimpleNamespace(config=config, inner_time=inner_time, sentinel=sentinel)
    assert not sentinel.exists(), "recent_activity must never contact a remote"


@pytest.fixture
def mtime_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    (vault_root / CONTEXT_FILE).write_text("work\n", encoding="utf-8")
    config = RagmarkConfig.for_vault(vault_root)
    return SimpleNamespace(config=config, vault_root=vault_root)


# --- git-log path -----------------------------------------------------------


def test_git_log_window_default_and_extended(git_vault) -> None:
    default_result = recent_activity(config=git_vault.config)
    default_paths = {e.note_path for e in default_result}
    assert "old8.md" not in default_paths
    assert "recent6.md" in default_paths

    extended_result = recent_activity(days=10, config=git_vault.config)
    extended_paths = {e.note_path for e in extended_result}
    assert "old8.md" in extended_paths
    assert "recent6.md" in extended_paths


def test_git_log_is_primary_not_mtime(git_vault) -> None:
    result = recent_activity(days=10, limit=50, config=git_vault.config)
    by_path = {e.note_path: e for e in result}

    for rel, dt in git_vault.note_times.items():
        if rel in by_path:
            assert by_path[rel].modified == _iso(dt)

    items = sorted(git_vault.note_times.items(), key=lambda kv: kv[0])
    items.sort(key=lambda kv: kv[1], reverse=True)
    expected_order = [rel for rel, _ in items if rel in by_path]
    assert [e.note_path for e in result] == expected_order


def test_note_committed_twice_appears_once_with_latest_time(git_vault) -> None:
    result = recent_activity(config=git_vault.config)
    matches = [e for e in result if e.note_path == "twice.md"]
    assert len(matches) == 1
    assert matches[0].modified == _iso(git_vault.note_times["twice.md"])
    assert _MODIFIED_RE.fullmatch(matches[0].modified)


def test_same_commit_tie_break_by_note_path_ascending(git_vault) -> None:
    result = recent_activity(config=git_vault.config)
    ordered = [e.note_path for e in result if e.note_path in ("same-a.md", "same-b.md")]
    assert ordered == ["same-a.md", "same-b.md"]


def test_deleted_note_does_not_appear(git_vault) -> None:
    result = recent_activity(config=git_vault.config)
    assert "deleted.md" not in {e.note_path for e in result}


def test_symlink_note_never_appears_on_git_path(git_vault) -> None:
    result = recent_activity(config=git_vault.config)
    assert "symlink.md" not in {e.note_path for e in result}


def test_malformed_frontmatter_reports_empty_first_line(git_vault) -> None:
    result = recent_activity(config=git_vault.config)
    entry = next(e for e in result if e.note_path == "malformed.md")
    assert entry.first_line == ""


def test_first_line_after_blank_line_is_verbatim_heading(git_vault) -> None:
    result = recent_activity(config=git_vault.config)
    entry = next(e for e in result if e.note_path == "firstline.md")
    assert entry.first_line == "# Heading First"


def test_empty_body_first_line_is_empty_string(git_vault) -> None:
    result = recent_activity(config=git_vault.config)
    entry = next(e for e in result if e.note_path == "emptybody.md")
    assert entry.first_line == ""


def test_non_note_committed_files_never_appear(git_vault) -> None:
    config = dataclasses.replace(git_vault.config, excluded_dirs=frozenset({"drafts"}))
    result = recent_activity(config=config)
    paths = {e.note_path for e in result}
    assert ".vault-context" not in paths
    assert "notes.txt" not in paths
    assert ".claude/x.md" not in paths
    assert "drafts/excluded.md" not in paths


def test_uncommitted_changes_not_reported_on_git_path(git_vault) -> None:
    (git_vault.repo_root / "untracked.md").write_text("untracked content\n", encoding="utf-8")
    (git_vault.repo_root / "old8.md").write_text("edited uncommitted\n", encoding="utf-8")

    result = recent_activity(config=git_vault.config)
    paths = {e.note_path for e in result}
    assert "untracked.md" not in paths
    assert "old8.md" not in paths


def test_git_unavailable_falls_back_to_mtime(
    git_vault, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty_path_dir = tmp_path / "empty-path"
    empty_path_dir.mkdir()
    monkeypatch.setenv("PATH", str(empty_path_dir))

    result = recent_activity(config=git_vault.config)
    by_path = {e.note_path: e for e in result}

    assert "symlink.md" not in by_path

    # old8.md has the globally oldest commit time, so mtime-reversal gives it
    # the newest mtime -- in the default window only via mtime, not commit time.
    oldest_rel = min(git_vault.note_times, key=lambda r: git_vault.note_times[r])
    assert oldest_rel in by_path
    expected_mtime = (git_vault.repo_root / oldest_rel).stat().st_mtime
    expected = datetime.fromtimestamp(expected_mtime, tz=UTC).isoformat(timespec="seconds")
    assert by_path[oldest_rel].modified == expected


@pytest.mark.gating
def test_work_context_hides_personal_note_git_path(git_vault) -> None:
    work_result = recent_activity(config=git_vault.config)
    assert "personal/secret.md" not in {e.note_path for e in work_result}

    (git_vault.repo_root / CONTEXT_FILE).write_text("personal\n", encoding="utf-8")
    personal_result = recent_activity(config=git_vault.config)
    assert "personal/secret.md" in {e.note_path for e in personal_result}


@pytest.mark.parametrize(
    ("days", "limit"),
    [(0, DEFAULT_LIMIT), (-1, DEFAULT_LIMIT), (DEFAULT_DAYS, 0), (DEFAULT_DAYS, -1)],
)
def test_non_positive_days_or_limit_returns_empty(git_vault, days: int, limit: int) -> None:
    assert recent_activity(days=days, limit=limit, config=git_vault.config) == []


def test_gate_then_clamp_50_of_51_visible(git_vault_51) -> None:
    result = recent_activity(limit=60, config=git_vault_51.config)
    assert len(result) == 50
    assert [e.note_path for e in result] == [f"bulk-{i:03d}.md" for i in range(50)]


def test_subdirectory_vault_translates_paths_and_excludes_outside(git_vault_subdir) -> None:
    result = recent_activity(config=git_vault_subdir.config)
    by_path = {e.note_path: e for e in result}
    assert "outside.md" not in by_path
    assert "notes/a.md" in by_path
    assert by_path["notes/a.md"].modified == _iso(git_vault_subdir.inner_time)


def test_non_ascii_note_names_reported_on_git_path(tmp_path: Path) -> None:
    repo_root, env, sentinel = _setup_repo(tmp_path, "repo-unicode")
    vault_root = repo_root / "vaulté"
    note = vault_root / "notes" / "café — idea.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ndescription: x\n---\nCafé body\n", encoding="utf-8")
    commit_time = datetime.now(UTC) - timedelta(days=1)
    _commit(repo_root, env, commit_time, "non-ascii note")
    wrong_mtime = (commit_time - timedelta(days=2)).timestamp()
    os.utime(note, (wrong_mtime, wrong_mtime))

    result = recent_activity(config=RagmarkConfig.for_vault(vault_root))
    by_path = {e.note_path: e for e in result}
    assert set(by_path) == {"notes/café — idea.md"}
    assert by_path["notes/café — idea.md"].modified == _iso(commit_time)
    assert by_path["notes/café — idea.md"].first_line == "Café body"
    assert not sentinel.exists()


# --- mtime fallback path ------------------------------------------------------


def test_mtime_fallback_window_and_order(mtime_vault) -> None:
    vault_root = mtime_vault.vault_root
    now = datetime.now(UTC)

    old = vault_root / "old8.md"
    old.write_text("old content\n", encoding="utf-8")
    old_ts = (now - timedelta(days=8)).timestamp()
    os.utime(old, (old_ts, old_ts))

    mid = vault_root / "mid3.md"
    mid.write_text("mid content\n", encoding="utf-8")
    mid_ts = (now - timedelta(days=3)).timestamp()
    os.utime(mid, (mid_ts, mid_ts))

    recent = vault_root / "recent6.md"
    recent.write_text("recent content\n", encoding="utf-8")
    recent_ts = (now - timedelta(days=6)).timestamp()
    os.utime(recent, (recent_ts, recent_ts))

    result = recent_activity(config=mtime_vault.config)
    paths = [e.note_path for e in result]
    assert "old8.md" not in paths
    assert paths == ["mid3.md", "recent6.md"]
    assert _MODIFIED_RE.fullmatch(result[0].modified)


def test_mtime_fallback_entry_shape(mtime_vault) -> None:
    vault_root = mtime_vault.vault_root
    note_dir = vault_root / "notes"
    note_dir.mkdir()
    note = note_dir / "heading.md"
    note.write_text("---\ndescription: x\n---\n\n# Heading\nbody\n", encoding="utf-8")
    mtime = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0)
    os.utime(note, (mtime.timestamp(), mtime.timestamp()))

    result = recent_activity(config=mtime_vault.config)
    by_path = {e.note_path: e for e in result}
    entry = by_path["notes/heading.md"]
    assert entry.first_line == "# Heading"
    assert _MODIFIED_RE.fullmatch(entry.modified)
    assert entry.modified == _iso(mtime)


def test_mtime_fallback_excludes_non_notes(mtime_vault) -> None:
    vault_root = mtime_vault.vault_root
    (vault_root / "notes.txt").write_text("not a note\n", encoding="utf-8")
    claude_dir = vault_root / ".claude"
    claude_dir.mkdir()
    (claude_dir / "x.md").write_text("hidden\n", encoding="utf-8")

    result = recent_activity(config=mtime_vault.config)
    paths = {e.note_path for e in result}
    assert "notes.txt" not in paths
    assert ".claude/x.md" not in paths


@pytest.mark.gating
def test_mtime_fallback_context_gating(mtime_vault) -> None:
    vault_root = mtime_vault.vault_root
    personal_dir = vault_root / "personal"
    personal_dir.mkdir()
    (personal_dir / "secret.md").write_text("secret\n", encoding="utf-8")

    (vault_root / CONTEXT_FILE).write_text("work\n", encoding="utf-8")
    work_result = recent_activity(config=mtime_vault.config)
    assert "personal/secret.md" not in {e.note_path for e in work_result}

    (vault_root / CONTEXT_FILE).write_text("personal\n", encoding="utf-8")
    personal_result = recent_activity(config=mtime_vault.config)
    assert "personal/secret.md" in {e.note_path for e in personal_result}
