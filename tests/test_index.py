"""Index build/refresh: mtime-gated incremental pass, ruler binding, corruption gating.

Cacheless tier (the gate for this change): a small deterministic stub `Embedder`
records every text handed to `count_tokens`, so the ruler-binding assertions catch
a swap back to a character-proxy ruler. The one `@pytest.mark.model` test repeats
the ruler assertion against the real fastembed model; the autouse fixture in
`conftest.py` skips it when no warm cache is present.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from ragmark import index
from ragmark.config import RagmarkConfig
from ragmark.embed import Embedder, FastembedEmbedder
from ragmark.model import ModelIdentity
from ragmark.store import IndexCorruptionError, IndexStore

DIM = 4

BASE_MTIME = 1_700_000_000_000_000_000

NOTE_A = "# Note A\n\nSome content about apples and oranges.\n"
NOTE_B = "# Note B\n\nSome content about bananas and pears.\n"
BAD_FRONTMATTER = "---\nkey: [unterminated\n---\n# Bad\n\nBody text despite bad frontmatter.\n"


class RecordingEmbedder(Embedder):
    """Deterministic stub ruler — records every text handed to `count_tokens`."""

    def __init__(self) -> None:
        self.count_tokens_calls: list[str] = []

    def identity(self) -> ModelIdentity:
        return ModelIdentity(name="stub", dim=DIM, version="1")

    def embed(self, texts):
        return np.array(
            [[float((hash(text) >> (8 * i)) % 97) for i in range(DIM)] for text in texts],
            dtype=np.float32,
        )

    def count_tokens(self, text: str) -> int:
        self.count_tokens_calls.append(text)
        return max(1, len(text.split()))


def make_config(tmp_path: Path) -> RagmarkConfig:
    vault = tmp_path / "vault"
    vault.mkdir()
    return RagmarkConfig.for_vault(vault, index_dir=tmp_path / "index")


def write_note(config: RagmarkConfig, rel: str, text: str, mtime_ns: int) -> Path:
    path = config.vault_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def seed_vault(config: RagmarkConfig) -> None:
    write_note(config, "a.md", NOTE_A, BASE_MTIME)
    write_note(config, "b.md", NOTE_B, BASE_MTIME)


def assert_conservation(store: IndexStore) -> None:
    conn = store.connect()
    n = store.chunk_count(conn)
    vectors = store.load_vectors()
    if n == 0:
        assert vectors is None
        return
    assert vectors is not None
    assert vectors.shape[0] == n
    rows = sorted(row for _, row in store.ordered_chunk_ids(conn))
    assert rows == list(range(n))


# --- ruler binding ------------------------------------------------------------


def test_token_count_is_bound_to_the_injected_embedders_ruler(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_vault(config)
    store = IndexStore(config.index_dir)
    embedder = RecordingEmbedder()

    index.reindex(config, store, embedder)

    conn = store.connect()
    rows = conn.execute("SELECT text, token_count FROM chunks").fetchall()
    assert rows
    for text, token_count in rows:
        assert token_count == embedder.count_tokens(text)
    assert embedder.count_tokens_calls


@pytest.mark.model
def test_token_count_matches_the_real_embedders_ruler(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_vault(config)
    store = IndexStore(config.index_dir)
    embedder = FastembedEmbedder()

    index.reindex(config, store, embedder)

    conn = store.connect()
    rows = conn.execute("SELECT text, token_count FROM chunks").fetchall()
    assert rows
    for text, token_count in rows:
        assert token_count == embedder.count_tokens(text)


# --- conservation --------------------------------------------------------------


def test_reindex_conserves_chunk_and_vector_rows(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_vault(config)
    store = IndexStore(config.index_dir)
    embedder = RecordingEmbedder()

    report = index.reindex(config, store, embedder)

    assert report.added == 2
    assert report.updated == 0
    assert report.removed == 0
    assert report.defects == ()
    assert_conservation(store)


# --- incremental refresh --------------------------------------------------------


def test_incremental_refresh_touch_then_change_then_delete(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_vault(config)
    store = IndexStore(config.index_dir)
    embedder = RecordingEmbedder()

    index.reindex(config, store, embedder)
    assert_conservation(store)

    touched_mtime = BASE_MTIME + 1_000_000
    path_a = config.vault_root / "a.md"
    os.utime(path_a, ns=(touched_mtime, touched_mtime))

    report = index.refresh(config, store, embedder)
    assert report.unchanged == 2
    assert report.updated == 0
    assert report.added == 0
    assert report.removed == 0
    assert_conservation(store)

    conn = store.connect()
    notes = store.read_notes(conn)
    assert notes["a.md"][1] == touched_mtime

    changed_mtime = BASE_MTIME + 2_000_000
    write_note(config, "a.md", "# Note A\n\nCompletely different content now.\n", changed_mtime)

    report = index.refresh(config, store, embedder)
    assert report.updated == 1
    assert report.unchanged == 1
    assert report.added == 0
    assert report.removed == 0
    assert_conservation(store)

    (config.vault_root / "b.md").unlink()
    report = index.refresh(config, store, embedder)
    assert report.removed == 1
    assert report.added == 0
    assert report.updated == 0
    conn = store.connect()
    remaining_notes = {
        row[0] for row in conn.execute("SELECT DISTINCT note_path FROM chunks").fetchall()
    }
    assert "b.md" not in remaining_notes
    assert_conservation(store)


# --- defects --------------------------------------------------------------------


def test_malformed_frontmatter_is_indexed_as_a_defect(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    write_note(config, "a.md", NOTE_A, BASE_MTIME)
    write_note(config, "bad.md", BAD_FRONTMATTER, BASE_MTIME)
    store = IndexStore(config.index_dir)
    embedder = RecordingEmbedder()

    report = index.reindex(config, store, embedder)

    assert any("bad.md" in defect for defect in report.defects)

    conn = store.connect()
    bad_rows = conn.execute(
        "SELECT heading, text FROM chunks WHERE note_path = ? ORDER BY chunk_index", ("bad.md",)
    ).fetchall()
    assert bad_rows
    # empty NoteMeta means no standalone description chunk — every chunk's text
    # comes from the raw body (frontmatter delimiters included, since the whole
    # file is treated as body when frontmatter parsing fails).
    assert any(heading == "Bad" for heading, _ in bad_rows)
    assert not any(text == BAD_FRONTMATTER for _, text in bad_rows)

    a_row_count = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE note_path = ?", ("a.md",)
    ).fetchone()[0]
    assert a_row_count > 0
    assert_conservation(store)


# --- corruption vs staleness -----------------------------------------------------


def test_unreadable_vectors_file_is_corruption_not_healed(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_vault(config)
    store = IndexStore(config.index_dir)
    embedder = RecordingEmbedder()
    index.reindex(config, store, embedder)

    store.vectors_path.write_bytes(b"not a numpy file at all")
    before_db = store.db_path.read_bytes()
    before_vectors = store.vectors_path.read_bytes()

    with pytest.raises(IndexCorruptionError, match=r"ragmark index --force"):
        index.refresh(config, store, embedder)

    assert store.db_path.read_bytes() == before_db
    assert store.vectors_path.read_bytes() == before_vectors

    report = index.reindex(config, store, embedder)
    assert report.added == 2
    assert_conservation(store)


def test_mismatched_row_counts_is_corruption_not_healed(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    seed_vault(config)
    store = IndexStore(config.index_dir)
    embedder = RecordingEmbedder()
    index.reindex(config, store, embedder)

    conn = store.connect()
    a_chunk_id = conn.execute(
        "SELECT chunk_id FROM chunks WHERE note_path = ? LIMIT 1", ("a.md",)
    ).fetchone()[0]
    with conn:
        conn.execute("DELETE FROM chunks WHERE chunk_id = ?", (a_chunk_id,))

    before_db = store.db_path.read_bytes()
    before_vectors = store.vectors_path.read_bytes()

    with pytest.raises(IndexCorruptionError, match=r"ragmark index --force"):
        index.refresh(config, store, embedder)

    assert store.db_path.read_bytes() == before_db
    assert store.vectors_path.read_bytes() == before_vectors

    report = index.reindex(config, store, embedder)
    assert report.added == 2
    assert_conservation(store)


# --- unbuilt is not corrupt -------------------------------------------------------


def test_refresh_builds_an_unbuilt_empty_vault(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    store = IndexStore(config.index_dir)
    embedder = RecordingEmbedder()

    report = index.refresh(config, store, embedder)

    assert report == index.RefreshReport(added=0, updated=0, removed=0, unchanged=0, defects=())
    assert not store.vectors_path.exists()
