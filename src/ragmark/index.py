"""Index build and refresh — mtime-gated, incremental (owed to slices).

The staleness contract (the-vault#140, decision 7): every QUERY runs a cheap
mtime sweep first; only files newer than their recorded `mtime_ns` get
sha256-checked and incrementally re-embedded. A stale index becomes
impossible rather than procedural — the predecessor auto-healed only a
MISSING index and was 44 notes stale at survey time (the-vault#137).

`reindex(force=True)` remains for full rebuilds (model swap, schema bump,
corruption healing).
"""

from __future__ import annotations

from dataclasses import dataclass

from ragmark.config import RagmarkConfig
from ragmark.embed import Embedder
from ragmark.store import IndexStore


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """What one refresh pass did (also where parse defects surface)."""

    added: int
    updated: int
    removed: int
    unchanged: int
    defects: tuple[str, ...]


def refresh(config: RagmarkConfig, store: IndexStore, embedder: Embedder) -> RefreshReport:
    """Bring the index up to date with the vault (incremental, mtime-gated)."""
    raise NotImplementedError("build slice: mtime-gated refresh (the-vault#140 d7)")


def reindex(config: RagmarkConfig, store: IndexStore, embedder: Embedder) -> RefreshReport:
    """Full rebuild: drop the derived layer and re-embed everything."""
    raise NotImplementedError("build slice: full rebuild (the-vault#140 d7)")
