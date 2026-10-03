"""Recent activity — "what moved lately", without a query to aim.

Decided shape (the-vault#142, accepted live): `{note_path, modified,
first_line}`, newest first, **git-log-backed** — the vault is always a repo,
and mtimes lie after a fresh sync — with an mtime fallback for non-repo
vaults. Results are context-gated like every other surface.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta

from ragmark import gate, parse
from ragmark.config import RagmarkConfig
from ragmark.model import ActivityEntry

DEFAULT_DAYS = 7
DEFAULT_LIMIT = 20
MAX_LIMIT = 50

_MARKER = "\x01"


def recent_activity(
    days: int = DEFAULT_DAYS,
    limit: int = DEFAULT_LIMIT,
    *,
    config: RagmarkConfig,
) -> list[ActivityEntry]:
    """Context-visible notes changed in the last *days*, newest first."""
    if days <= 0 or limit <= 0:
        return []

    cutoff = (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0)

    candidates = _git_candidates(config, cutoff)
    if candidates is None:
        candidates = _mtime_candidates(config, cutoff)

    visible_paths = gate.filter_visible(list(candidates.keys()), config)

    entries: list[ActivityEntry] = []
    for rel_path in visible_paths:
        try:
            text = gate.read_note(rel_path, config)
        except gate.VaultAccessError:
            continue
        try:
            _, body = parse.parse_note(text)
            first_line = _first_nonempty_line(body)
        except parse.FrontmatterError:
            first_line = ""
        entries.append(
            ActivityEntry(
                note_path=rel_path,
                modified=candidates[rel_path].isoformat(timespec="seconds"),
                first_line=first_line,
            )
        )

    entries.sort(key=lambda e: e.note_path)
    entries.sort(key=lambda e: e.modified, reverse=True)
    return entries[: min(limit, MAX_LIMIT)]


def _first_nonempty_line(body: str) -> str:
    for line in body.splitlines():
        if line.strip():
            return line
    return ""


def _git_candidates(config: RagmarkConfig, cutoff: datetime) -> dict[str, datetime] | None:
    """Vault-relative path -> latest in-window committer time, or None if git is unusable.

    Local-only: `rev-parse --show-prefix` and `log` never contact a remote. Paths are
    read NUL-delimited (`-z`) with `core.quotePath` off, so non-ASCII names arrive
    verbatim rather than quoted and octal-escaped.
    """
    vault_root = config.vault_root
    git = ["git", "-C", str(vault_root), "-c", "core.quotePath=false"]
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    env.pop("GIT_INDEX_FILE", None)
    env["GIT_NO_LAZY_FETCH"] = "1"
    try:
        prefix_result = subprocess.run(
            [*git, "rev-parse", "--show-prefix"],
            capture_output=True,
            encoding="utf-8",
            errors="surrogateescape",
            check=True,
            env=env,
        )
        log_result = subprocess.run(
            [
                *git,
                "log",
                f"--since={cutoff.isoformat()}",
                f"--pretty=format:{_MARKER}%cI",
                "--name-only",
                "--no-renames",
                "-z",
                "--",
                ".",
            ],
            capture_output=True,
            encoding="utf-8",
            errors="surrogateescape",
            check=True,
            env=env,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    prefix = prefix_result.stdout.rstrip("\n")

    candidates: dict[str, datetime] = {}
    current_dt: datetime | None = None
    for token in log_result.stdout.split("\0"):
        token = token.lstrip("\n")
        if token.startswith(_MARKER):
            header, _, token = token[1:].partition("\n")
            current_dt = datetime.fromisoformat(header).astimezone(UTC)
        if not token or current_dt is None:
            continue
        if prefix and not token.startswith(prefix):
            continue
        if current_dt < cutoff:
            continue
        rel_path = token[len(prefix) :] if prefix else token
        resolved = vault_root / rel_path
        if not gate.is_indexable_note(resolved, config):
            continue
        if rel_path not in candidates or current_dt > candidates[rel_path]:
            candidates[rel_path] = current_dt
    return candidates


def _mtime_candidates(config: RagmarkConfig, cutoff: datetime) -> dict[str, datetime]:
    """Vault-relative path -> mtime, for every indexable note in the window."""
    root = config.vault_root
    candidates: dict[str, datetime] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if not gate.is_indexable_note(path, config):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        dt = datetime.fromtimestamp(mtime, tz=UTC)
        if dt < cutoff:
            continue
        rel_path = path.relative_to(root).as_posix()
        candidates[rel_path] = dt
    return candidates
