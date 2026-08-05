"""Index build and refresh — mtime-gated, incremental (owed to slices).

The staleness contract (the-vault#140, decision 7): every QUERY runs a cheap
mtime sweep first; only files newer than their recorded `mtime_ns` get
sha256-checked and incrementally re-embedded. A stale index becomes
impossible rather than procedural — the predecessor auto-healed only a
MISSING index and was 44 notes stale at survey time (the-vault#137).

`reindex` remains for full rebuilds (model swap, schema bump, corruption
healing) — the CLI's `--force` flag selects it over `refresh`; `refresh`
never self-heals an incoherent index (see `IndexCorruptionError`).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ragmark import chunk as chunk_mod
from ragmark import gate, parse
from ragmark.config import RagmarkConfig
from ragmark.embed import Embedder
from ragmark.model import NoteMeta
from ragmark.store import IndexCorruptionError, IndexStore

_CORRUPTION_REMEDY = "rebuild with `ragmark index --force`"


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """What one refresh pass did (also where parse defects surface)."""

    added: int
    updated: int
    removed: int
    unchanged: int
    defects: tuple[str, ...]


def refresh(config: RagmarkConfig, store: IndexStore, embedder: Embedder) -> RefreshReport:
    """Bring the index up to date with the vault (incremental, mtime-gated).

    Heals staleness only: an incoherent on-disk pair (built, but the vectors
    and chunk rows disagree) raises `IndexCorruptionError` rather than being
    silently rebuilt — the remedy is `reindex` (`ragmark index --force`).
    """
    try:
        conn = store.connect()
        identity = store.read_identity(conn)
        chunk_total = store.chunk_count(conn)
    except sqlite3.DatabaseError as exc:
        raise IndexCorruptionError(f"index metadata is unreadable; {_CORRUPTION_REMEDY}") from exc

    is_built = identity is not None and chunk_total > 0
    old_vectors: Any | None = None
    if is_built:
        try:
            old_vectors = store.load_vectors()
        except (ValueError, OSError, EOFError) as exc:
            raise IndexCorruptionError(
                f"index vectors are unreadable; {_CORRUPTION_REMEDY}"
            ) from exc
        if old_vectors is None:
            raise IndexCorruptionError(f"index vectors are missing; {_CORRUPTION_REMEDY}")
        if old_vectors.shape[0] != chunk_total:
            raise IndexCorruptionError(
                f"index vectors ({old_vectors.shape[0]} rows) disagree with "
                f"{chunk_total} chunk rows; {_CORRUPTION_REMEDY}"
            )

    store.check_identity(conn, embedder.identity())
    if identity is None:
        store.write_identity(conn, embedder.identity())

    prior_notes = store.read_notes(conn)
    return _run_pass(config, store, conn, embedder, prior_notes, old_vectors)


def reindex(config: RagmarkConfig, store: IndexStore, embedder: Embedder) -> RefreshReport:
    """Full rebuild: drop the derived layer and re-embed everything.

    Never runs the corruption gate — it is the remedy that gate points to.
    """
    if store.db_path.exists():
        store.db_path.unlink()
    if store.vectors_path.exists():
        store.vectors_path.unlink()

    conn = store.connect()
    store.write_identity(conn, embedder.identity())
    return _run_pass(config, store, conn, embedder, {}, None)


def _run_pass(
    config: RagmarkConfig,
    store: IndexStore,
    conn: sqlite3.Connection,
    embedder: Embedder,
    prior_notes: dict[str, tuple[str, int]],
    old_vectors: Any | None,
) -> RefreshReport:
    added = updated = removed = unchanged = 0
    defects: list[str] = []
    pending_texts: dict[str, str] = {}
    walked_paths: set[str] = set()

    for resolved in _walk_notes(config):
        rel_path = resolved.relative_to(config.vault_root).as_posix()
        walked_paths.add(rel_path)
        mtime_ns = resolved.stat().st_mtime_ns
        prior = prior_notes.get(rel_path)

        if prior is not None and prior[1] == mtime_ns:
            unchanged += 1
            continue

        data = resolved.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()

        if prior is not None and prior[0] == sha256:
            store.write_note(conn, rel_path, sha256, mtime_ns)
            unchanged += 1
            continue

        text = data.decode("utf-8")
        try:
            meta, body = parse.parse_note(text)
        except parse.FrontmatterError as exc:
            defects.append(f"{rel_path}: {exc}")
            meta, body = NoteMeta(None, (), ()), text

        chunks = chunk_mod.chunk_note(rel_path, body, meta, embedder.count_tokens)
        store.replace_chunks(conn, rel_path, chunks)
        store.write_note(conn, rel_path, sha256, mtime_ns)
        pending_texts.update({c.chunk_id: c.text for c in chunks})

        if prior is None:
            added += 1
        else:
            updated += 1

    for rel_path in set(prior_notes) - walked_paths:
        store.replace_chunks(conn, rel_path, [])
        store.delete_note(conn, rel_path)
        removed += 1

    _recompact_vectors(store, conn, embedder, pending_texts, old_vectors)

    return RefreshReport(
        added=added,
        updated=updated,
        removed=removed,
        unchanged=unchanged,
        defects=tuple(defects),
    )


def _recompact_vectors(
    store: IndexStore,
    conn: sqlite3.Connection,
    embedder: Embedder,
    pending_texts: dict[str, str],
    old_vectors: Any | None,
) -> None:
    """Full recompaction: renumber `vector_row` densely and rewrite the matrix.

    Chunks untouched this pass keep their prior `vector_row`, so their vector
    carries over from `old_vectors` unre-embedded; chunks written this pass
    (`vector_row == -1`, set by `replace_chunks`) draw from this pass's fresh
    embeddings.
    """
    import numpy as np

    new_vectors: dict[str, Any] = {}
    if pending_texts:
        ids = list(pending_texts)
        embedded = embedder.embed([pending_texts[chunk_id] for chunk_id in ids])
        new_vectors = dict(zip(ids, embedded, strict=True))

    ordered = store.ordered_chunk_ids(conn)
    if not ordered:
        return

    dim = embedder.identity().dim
    matrix = np.empty((len(ordered), dim), dtype=np.float32)
    assignments: dict[str, int] = {}
    for row, (chunk_id, old_row) in enumerate(ordered):
        matrix[row] = new_vectors[chunk_id] if old_row == -1 else old_vectors[old_row]
        assignments[chunk_id] = row

    store.assign_vector_rows(conn, assignments)
    store.save_vectors(matrix)


def _walk_notes(config: RagmarkConfig) -> list[Path]:
    """Walk `config.vault_root`, pruning excluded/dot directories, filtering
    to indexable notes. Never `rglob("*.md")`: it would descend into `.git/`
    and `.ragmark/` before filtering."""
    notes: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(config.vault_root):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name not in config.excluded_dirs
        ]
        for filename in filenames:
            resolved = Path(dirpath) / filename
            if gate.is_indexable_note(resolved, config):
                notes.append(resolved)
    return notes
