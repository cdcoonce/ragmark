"""Index store — flat npy vectors + one stdlib-SQLite metadata file.

Decided layout (the-vault#140, decision 6): vectors stay a flat numpy file
(brute-force cosine over the full matrix measured 0.34–2.4 ms/query at
10–50k chunks — the-vault#138); chunk metadata, tags/aliases, parent refs,
note hashes, and the manifest live in ONE SQLite file so filters and the
lexical leg get real queries.

Two properties are implemented here in the seed because they are pure
infrastructure and the correctness contract leans on them:

- **Atomic writes.** Every artifact lands via temp-file + `os.replace` in the
  same directory. The predecessor's docstring promised this and its code did
  three direct overwrites; corruption then presented as a silent full rebuild
  (the-vault#137). Here a torn write cannot produce a readable-but-wrong file.
- **Identity check.** The store records the embedding `ModelIdentity` and
  refuses to serve an index built by a different model — a detected error
  prompting rebuild, never a silent shape mismatch.

Coherence between the two files is the conservation invariant's job (chunk
rows ↔ vector rows, the-vault#144). `index.refresh` heals staleness only;
incoherence between the two files (a torn pair) is a detected,
non-self-healing error (`IndexCorruptionError`) whose remedy is
`ragmark index --force`.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from ragmark.model import Chunk, ModelIdentity

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    note_path TEXT PRIMARY KEY,
    sha256    TEXT NOT NULL,
    mtime_ns  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id    TEXT PRIMARY KEY,
    note_path   TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    heading     TEXT,
    parent_ref  TEXT,
    text        TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    vector_row  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_note ON chunks (note_path);
"""


class IndexIdentityError(Exception):
    """The on-disk index was built by a different model than requested."""


class IndexCorruptionError(Exception):
    """The on-disk index is BUILT but internally incoherent — never self-healed.

    Raised only when a model identity row and at least one chunk row are
    already present, yet `vectors.npy` disagrees with them (missing,
    unreadable, or a mismatched row count) or the metadata database itself is
    unreadable. `index.refresh` heals staleness, not incoherence — the
    remedy is a forced rebuild, `ragmark index --force`.
    """


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write *data* to *path* via temp + rename in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    tmp = Path(tmp_name)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class IndexStore:
    """One vault's derived index under `config.index_dir`."""

    def __init__(self, index_dir: Path) -> None:
        self.index_dir = index_dir
        self.db_path = index_dir / "ragmark.db"
        self.vectors_path = index_dir / "vectors.npy"

    def connect(self) -> sqlite3.Connection:
        """Open (creating if needed) the metadata database."""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(_SCHEMA)
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        return conn

    def read_identity(self, conn: sqlite3.Connection) -> ModelIdentity | None:
        """The model identity this index was built with, or None if unbuilt."""
        rows = dict(
            conn.execute(
                "SELECT key, value FROM meta WHERE key IN "
                "('model_name', 'model_dim', 'model_version')"
            ).fetchall()
        )
        if len(rows) < 3:
            return None
        return ModelIdentity(
            name=rows["model_name"],
            dim=int(rows["model_dim"]),
            version=rows["model_version"],
        )

    def write_identity(self, conn: sqlite3.Connection, identity: ModelIdentity) -> None:
        """Record the building model's identity in the manifest."""
        conn.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            [
                ("model_name", identity.name),
                ("model_dim", str(identity.dim)),
                ("model_version", identity.version),
            ],
        )
        conn.commit()

    def check_identity(self, conn: sqlite3.Connection, expected: ModelIdentity) -> None:
        """Refuse to serve an index built by a different model.

        A mismatch raises `IndexIdentityError` — the caller's remedy is a
        forced rebuild, and the error says so. An unbuilt index passes: there
        is nothing to mismatch yet.
        """
        recorded = self.read_identity(conn)
        if recorded is None or recorded == expected:
            return
        raise IndexIdentityError(
            f"index at {self.db_path} was built with {recorded.name} "
            f"(dim {recorded.dim}, v{recorded.version}); requested {expected.name} "
            f"(dim {expected.dim}, v{expected.version}). Rebuild with "
            "`ragmark index --force`."
        )

    def read_notes(self, conn: sqlite3.Connection) -> dict[str, tuple[str, int]]:
        """Every recorded note as `note_path -> (sha256, mtime_ns)`."""
        rows = conn.execute("SELECT note_path, sha256, mtime_ns FROM notes").fetchall()
        return {note_path: (sha256, mtime_ns) for note_path, sha256, mtime_ns in rows}

    def write_note(
        self, conn: sqlite3.Connection, note_path: str, sha256: str, mtime_ns: int
    ) -> None:
        """Insert or replace one note's recorded hash and mtime."""
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO notes (note_path, sha256, mtime_ns) VALUES (?, ?, ?)",
                (note_path, sha256, mtime_ns),
            )

    def delete_note(self, conn: sqlite3.Connection, note_path: str) -> None:
        """Remove one note's recorded row (its chunk rows are a separate call)."""
        with conn:
            conn.execute("DELETE FROM notes WHERE note_path = ?", (note_path,))

    def replace_chunks(self, conn: sqlite3.Connection, note_path: str, chunks: list[Chunk]) -> None:
        """Replace one note's chunk rows in a single transaction."""
        with conn:
            conn.execute("DELETE FROM chunks WHERE note_path = ?", (note_path,))
            conn.executemany(
                "INSERT INTO chunks (chunk_id, note_path, chunk_index, heading, "
                "parent_ref, text, token_count, vector_row) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.chunk_id,
                        c.note_path,
                        c.chunk_index,
                        c.heading,
                        c.parent_ref,
                        c.text,
                        c.token_count,
                        -1,  # vector_row is assigned when vectors are written
                    )
                    for c in chunks
                ],
            )

    def chunk_count(self, conn: sqlite3.Connection) -> int:
        """Number of chunk rows (one side of the conservation invariant)."""
        return int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def ordered_chunk_ids(self, conn: sqlite3.Connection) -> list[tuple[str, int]]:
        """Every chunk's `(chunk_id, vector_row)`, in dense-compaction order
        (`note_path` then `chunk_index`) — the read half of full recompaction."""
        rows = conn.execute(
            "SELECT chunk_id, vector_row FROM chunks ORDER BY note_path ASC, chunk_index ASC"
        ).fetchall()
        return [(chunk_id, vector_row) for chunk_id, vector_row in rows]

    def read_chunk_rows(
        self, conn: sqlite3.Connection
    ) -> list[tuple[str, str, str | None, str, int]]:
        """Every chunk as `(chunk_id, note_path, heading, text, vector_row)`.

        The read half both retrieval legs share: the lexical leg scores
        `text` directly (no FTS5 virtual table — the layout above is decided),
        and the vector leg joins `vector_row` into `vectors.npy`. Ordered like
        `ordered_chunk_ids` so a caller's iteration order is stable.
        """
        rows = conn.execute(
            "SELECT chunk_id, note_path, heading, text, vector_row FROM chunks "
            "ORDER BY note_path ASC, chunk_index ASC"
        ).fetchall()
        return [
            (chunk_id, note_path, heading, text, vector_row)
            for chunk_id, note_path, heading, text, vector_row in rows
        ]

    def assign_vector_rows(self, conn: sqlite3.Connection, vector_rows: dict[str, int]) -> None:
        """Write a dense `vector_row` renumbering computed from `ordered_chunk_ids`."""
        with conn:
            conn.executemany(
                "UPDATE chunks SET vector_row = ? WHERE chunk_id = ?",
                [(row, chunk_id) for chunk_id, row in vector_rows.items()],
            )

    def save_vectors(self, vectors: Any) -> None:
        """Persist the full vector matrix atomically (float32, N×dim)."""
        import io

        import numpy as np

        buffer = io.BytesIO()
        np.save(buffer, np.asarray(vectors, dtype=np.float32))
        atomic_write_bytes(self.vectors_path, buffer.getvalue())

    def load_vectors(self) -> Any | None:
        """Load the vector matrix, or None when absent (unbuilt index)."""
        if not self.vectors_path.exists():
            return None
        import numpy as np

        return np.load(self.vectors_path)
