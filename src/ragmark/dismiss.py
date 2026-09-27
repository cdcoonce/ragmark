"""Dismissal store with content-hash staleness for weaklink suggestions.

Ported byte-for-byte from graphmark v0.9.1 ``src/graphmark/dismiss.py`` so that
dismissals graphmark already recorded survive graphmark's ``gaps()`` deprecation
(the-vault#143 decision 2). Where this module and graphmark's disagree, graphmark's
code wins (Charles's 2026-09-26 byte-compatibility decision). This module does not
import graphmark.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_DEFAULT_PATH = ".claude/data/connect-dismissed.json"


def weaklink_sig(a: str, b: str) -> str:
    return "weaklink|" + "|".join(sorted([a, b]))


def content_hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def record_dismissal(root: Path, a: str, b: str, *, path: str = _DEFAULT_PATH) -> None:
    dismissed_file = root / path
    dismissed_file.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if dismissed_file.exists():
        try:
            existing = json.loads(dismissed_file.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}
    sig = weaklink_sig(a, b)
    existing[sig] = {
        "a": a,
        "a_hash": content_hash(root / a),
        "b": b,
        "b_hash": content_hash(root / b),
    }
    dismissed_file.write_text(json.dumps(existing, indent=2))


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
        a_path = root / record["a"]
        b_path = root / record["b"]
        if (
            a_path.exists()
            and b_path.exists()
            and content_hash(a_path) == record["a_hash"]
            and content_hash(b_path) == record["b_hash"]
        ):
            active.add(sig)
    return active
