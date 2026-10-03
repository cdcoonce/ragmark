"""The index store: schema, model identity, atomicity."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

import pytest

from ragmark import gaps, index, search
from ragmark.config import RagmarkConfig
from ragmark.embed import Embedder
from ragmark.model import Chunk, ModelIdentity
from ragmark.store import IndexIdentityError, IndexStore, atomic_write_bytes

IDENTITY = ModelIdentity(name="BAAI/bge-small-en-v1.5", dim=384, version="0.8.0")
BASE_MTIME = 1_700_000_000_000_000_000
_PROSE_TOKEN_RE = re.compile(r"[a-z]+")


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


# --- vector matrix cache (one np.load per store until the file changes) -------


@pytest.fixture
def load_calls(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Spy on numpy.load; each entry is the path it was called with."""
    numpy = pytest.importorskip("numpy")
    real_load = numpy.load
    calls: list[Path] = []

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(Path(file))
        return real_load(file, *args, **kwargs)

    monkeypatch.setattr(numpy, "load", spy)
    return calls


def _matrix(rows: int, fill: float) -> Any:
    numpy = pytest.importorskip("numpy")
    return numpy.full((rows, 4), fill, dtype=numpy.float32)


def test_repeated_loads_on_one_store_read_the_file_once(tmp_path: Path, load_calls) -> None:
    numpy = pytest.importorskip("numpy")
    store = make_store(tmp_path)
    matrix = _matrix(3, 1.5)
    store.save_vectors(matrix)

    for _ in range(5):
        loaded = store.load_vectors()
        assert loaded is not None
        assert bool(numpy.array_equal(loaded, matrix))

    assert len(load_calls) == 1


def test_fresh_store_has_no_cached_matrix(tmp_path: Path, load_calls) -> None:
    make_store(tmp_path).save_vectors(_matrix(2, 1.0))
    load_calls.clear()

    assert make_store(tmp_path).load_vectors() is not None
    assert len(load_calls) == 1


def test_save_then_load_returns_new_values_for_same_shape_and_restored_mtime(
    tmp_path: Path, load_calls
) -> None:
    """save_vectors drops the cache: with the key forced equal, only that can reload."""
    numpy = pytest.importorskip("numpy")
    store = make_store(tmp_path)
    store.save_vectors(_matrix(3, 1.0))
    assert store.load_vectors() is not None
    before = store.vectors_path.stat()

    store.save_vectors(_matrix(3, 2.0))
    os.utime(store.vectors_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    loaded = store.load_vectors()

    assert loaded is not None
    assert bool(numpy.array_equal(loaded, _matrix(3, 2.0)))
    assert len(load_calls) == 2


def test_rewrite_with_new_size_through_second_store_is_picked_up(
    tmp_path: Path, load_calls
) -> None:
    numpy = pytest.importorskip("numpy")
    first = make_store(tmp_path)
    second = IndexStore(first.index_dir)
    first.save_vectors(_matrix(3, 1.0))
    assert first.load_vectors() is not None
    before = first.vectors_path.stat()

    second.save_vectors(_matrix(5, 2.0))
    os.utime(first.vectors_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    loaded = first.load_vectors()

    assert loaded is not None
    assert loaded.shape == (5, 4)
    assert bool(numpy.array_equal(loaded, _matrix(5, 2.0)))
    assert len(load_calls) == 2


def test_same_size_rewrite_with_new_mtime_is_reloaded(tmp_path: Path, load_calls) -> None:
    numpy = pytest.importorskip("numpy")
    first = make_store(tmp_path)
    second = IndexStore(first.index_dir)
    first.save_vectors(_matrix(3, 1.0))
    assert first.load_vectors() is not None
    before = first.vectors_path.stat()

    second.save_vectors(_matrix(3, 7.0))
    os.utime(first.vectors_path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    loaded = first.load_vectors()

    assert loaded is not None
    assert bool(numpy.array_equal(loaded, _matrix(3, 7.0)))
    assert len(load_calls) == 2


def test_key_is_read_before_the_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A rewrite landing mid-load must not pair the old matrix with the new file's key."""
    numpy = pytest.importorskip("numpy")
    first = make_store(tmp_path)
    second = IndexStore(first.index_dir)
    first.save_vectors(_matrix(3, 1.0))
    real_load = numpy.load
    calls: list[Path] = []

    def load_then_rewrite(file: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(Path(file))
        loaded = real_load(file, *args, **kwargs)
        if len(calls) == 1:
            second.save_vectors(_matrix(5, 2.0))
        return loaded

    monkeypatch.setattr(numpy, "load", load_then_rewrite)

    first_result = first.load_vectors()
    second_result = first.load_vectors()

    assert first_result is not None and first_result.shape == (3, 4)
    assert second_result is not None and second_result.shape == (5, 4)
    assert len(calls) == 2


def test_missing_file_is_none_and_never_serves_a_cached_matrix(tmp_path: Path, load_calls) -> None:
    store = make_store(tmp_path)
    assert store.load_vectors() is None
    assert load_calls == []

    store.save_vectors(_matrix(3, 1.0))
    assert store.load_vectors() is not None
    assert len(load_calls) == 1

    store.vectors_path.unlink()
    assert store.load_vectors() is None
    assert len(load_calls) == 1


# --- one load per gaps()/similar_notes run, never stale across writers --------


class _StubEmbedder(Embedder):
    """Deterministic bag-of-words stub: no fastembed, no model cache."""

    def identity(self) -> ModelIdentity:
        return ModelIdentity(name="stub", dim=64, version="1")

    def embed(self, texts: Any) -> Any:
        numpy = pytest.importorskip("numpy")
        texts = list(texts)
        matrix = numpy.zeros((len(texts), 64), dtype=numpy.float32)
        for row, text in enumerate(texts):
            for token in _PROSE_TOKEN_RE.findall(text.lower()):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                matrix[row, int.from_bytes(digest, "big") % 64] += 1.0
        return matrix

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


def _config(tmp_path: Path) -> RagmarkConfig:
    vault = tmp_path / "vault"
    vault.mkdir()
    return RagmarkConfig.for_vault(vault, index_dir=tmp_path / "index")


def _write_note(config: RagmarkConfig, rel: str, text: str, mtime_ns: int = BASE_MTIME) -> None:
    path = config.vault_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))


TOPICS = {
    "a.md": "kayaking and rivers and rapids",
    "b.md": "kayaking and rapids and canoes",
    "c.md": "glassblowing and furnaces",
    "d.md": "sourdough and starter and bread",
    "e.md": "telescopes and optics and lenses",
    "f.md": "beekeeping and hives and honey",
}


def _write_topic_vault(config: RagmarkConfig) -> None:
    for rel, topic in TOPICS.items():
        _write_note(config, rel, f"# {rel}\n\nThe note is about {topic}.\n")


def test_similar_notes_loads_vectors_once_across_many_notes(tmp_path: Path, load_calls) -> None:
    config = _config(tmp_path)
    _write_topic_vault(config)
    store = IndexStore(config.index_dir)
    index.reindex(config, store, _StubEmbedder())
    load_calls.clear()

    for rel in list(TOPICS)[:5]:
        assert search.similar_notes(rel, 8, config=config, store=store)

    assert len(load_calls) == 1


def test_search_auto_refresh_keeps_the_cache_fresh(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _write_topic_vault(config)
    store = IndexStore(config.index_dir)
    embedder = _StubEmbedder()
    search.search("kayaking", 8, config=config, store=store, embedder=embedder)
    search.similar_notes("a.md", 8, config=config, store=store)

    _write_note(
        config,
        "a.md",
        "# a.md\n\nThe note is about telescopes and optics and lenses.\n",
        BASE_MTIME + 10_000_000,
    )
    search.search("telescopes", 8, config=config, store=store, embedder=embedder)

    cached = search.similar_notes("a.md", 8, config=config, store=store)
    fresh = search.similar_notes("a.md", 8, config=config, store=IndexStore(config.index_dir))
    assert cached == fresh


def test_gaps_loads_vectors_once_and_matches_the_uncached_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, load_calls
) -> None:
    config = _config(tmp_path)
    _write_topic_vault(config)
    index.reindex(config, IndexStore(config.index_dir), _StubEmbedder())
    load_calls.clear()

    cached = gaps.gaps(config=config)
    assert len(load_calls) == 1

    def uncached_load_vectors(self: IndexStore) -> Any:
        """The pre-cache body: exists check, then np.load on every call."""
        if not self.vectors_path.exists():
            return None
        import numpy as np

        return np.load(self.vectors_path)

    monkeypatch.setattr(IndexStore, "load_vectors", uncached_load_vectors)
    load_calls.clear()
    uncached = gaps.gaps(config=config)

    assert cached == uncached
    assert len(load_calls) > 1
