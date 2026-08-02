"""The index store: schema, model identity, atomicity."""

from __future__ import annotations

from pathlib import Path

import pytest

from ragmark.model import Chunk, ModelIdentity
from ragmark.store import IndexIdentityError, IndexStore, atomic_write_bytes

IDENTITY = ModelIdentity(name="BAAI/bge-small-en-v1.5", dim=384, version="0.8.0")


def make_store(tmp_path: Path) -> IndexStore:
    return IndexStore(tmp_path / "index")


def test_connect_creates_schema(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    conn = store.connect()
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert {"meta", "notes", "chunks"} <= tables


def test_identity_roundtrip_and_check(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    conn = store.connect()

    assert store.read_identity(conn) is None
    store.check_identity(conn, IDENTITY)  # unbuilt index passes

    store.write_identity(conn, IDENTITY)
    assert store.read_identity(conn) == IDENTITY
    store.check_identity(conn, IDENTITY)  # same model passes


def test_identity_mismatch_is_a_detected_error(tmp_path: Path) -> None:
    """A model swap must refuse loudly, never shape-crash later (the-vault#140 d2)."""
    store = make_store(tmp_path)
    conn = store.connect()
    store.write_identity(conn, IDENTITY)

    other = ModelIdentity(name="BAAI/bge-base-en-v1.5", dim=768, version="0.8.0")
    with pytest.raises(IndexIdentityError, match="Rebuild"):
        store.check_identity(conn, other)


def test_replace_chunks_is_per_note_and_idempotent(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    conn = store.connect()

    def chunk(note: str, i: int) -> Chunk:
        return Chunk(
            chunk_id=f"{note}#{i}",
            note_path=note,
            chunk_index=i,
            heading=None,
            parent_ref=None,
            text=f"chunk {i}",
            token_count=2,
        )

    store.replace_chunks(conn, "a.md", [chunk("a.md", 0), chunk("a.md", 1)])
    store.replace_chunks(conn, "b.md", [chunk("b.md", 0)])
    assert store.chunk_count(conn) == 3

    store.replace_chunks(conn, "a.md", [chunk("a.md", 0)])
    assert store.chunk_count(conn) == 2


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "artifact.bin"
    atomic_write_bytes(target, b"first")
    atomic_write_bytes(target, b"second")

    assert target.read_bytes() == b"second"
    leftovers = [p for p in tmp_path.iterdir() if p.name != "artifact.bin"]
    assert leftovers == []


def test_vectors_roundtrip_and_absent_is_none(tmp_path: Path) -> None:
    numpy = pytest.importorskip("numpy")
    store = make_store(tmp_path)

    assert store.load_vectors() is None

    matrix = numpy.arange(12, dtype=numpy.float32).reshape(3, 4)
    store.save_vectors(matrix)
    loaded = store.load_vectors()
    assert loaded is not None
    assert loaded.dtype == numpy.float32
    assert loaded.shape == (3, 4)
    assert bool((loaded == matrix).all())
