"""Dismissal store with content-hash staleness for weaklink suggestions.

Ported byte-for-byte from graphmark v0.10.0 ``src/graphmark/dismiss.py`` so that
dismissals graphmark already recorded survive graphmark's ``gaps()`` deprecation
(the-vault#143 decision 2). Where this module and graphmark's disagree, graphmark's
code wins (Charles's 2026-09-26 byte-compatibility decision). This module does not
import graphmark.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_DEFAULT_PATH = ".claude/data/connect-dismissed.json"


def weaklink_sig(a: str, b: str) -> str:
    return "weaklink|" + "|".join(sorted([a, b]))


def content_hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _resolves_within(root: Path, rel: str) -> bool:
    try:
        return (root / rel).resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def record_dismissal(root: Path, a: str, b: str, *, path: str = _DEFAULT_PATH) -> None:
    if not _resolves_within(root, a):
        raise ValueError(f"record_dismissal: path resolves outside {root}: {a}")
    if not _resolves_within(root, b):
        raise ValueError(f"record_dismissal: path resolves outside {root}: {b}")
    dismissed_file = root / path
    try:
        a_hash = content_hash(root / a)
    except (FileNotFoundError, IsADirectoryError):
        raise ValueError(f"record_dismissal: note not found under {root}: {a}") from None
    try:
        b_hash = content_hash(root / b)
    except (FileNotFoundError, IsADirectoryError):
        raise ValueError(f"record_dismissal: note not found under {root}: {b}") from None
    dismissed_file.parent.mkdir(parents=True, exist_ok=True)
    existing = load_dismissed(root, path=path)
    sig = weaklink_sig(a, b)
    existing[sig] = {
        "a": a,
        "a_hash": a_hash,
        "b": b,
        "b_hash": b_hash,
    }
    temp_file = dismissed_file.parent / (dismissed_file.name + f".tmp{os.getpid()}")
    try:
        temp_file.write_text(json.dumps(existing, indent=2))
        temp_file.replace(dismissed_file)
    except Exception:
        if temp_file.exists():
            temp_file.unlink()
        raise


def load_dismissed(root: Path, *, path: str = _DEFAULT_PATH) -> dict:
    """Load the dismissal store, treating a corrupt or unreadable store as empty.

    Mirrors ``record_dismissal``'s guard: invalid JSON, an unreadable file, or a non-dict
    payload all mean "no active dismissals", never a crash.
    """
    dismissed_file = root / path
    if not dismissed_file.exists():
        return {}
    try:
        data = json.loads(dismissed_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def active_dismissed_sigs(root: Path, *, path: str = _DEFAULT_PATH) -> set[str]:
    dismissed = load_dismissed(root, path=path)
    active: set[str] = set()
    for sig, record in dismissed.items():
        if not isinstance(record, dict):
            continue
        a, b, a_hash, b_hash = (
            record.get("a"),
            record.get("b"),
            record.get("a_hash"),
            record.get("b_hash"),
        )
        if not all(isinstance(v, str) and v for v in (a, b, a_hash, b_hash)):
            continue
        if not _resolves_within(root, a) or not _resolves_within(root, b):
            continue
        a_path, b_path = root / a, root / b
        if (
            a_path.is_file()
            and b_path.is_file()
            and content_hash(a_path) == a_hash
            and content_hash(b_path) == b_hash
        ):
            active.add(sig)
    return active
