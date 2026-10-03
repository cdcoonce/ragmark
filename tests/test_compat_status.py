"""Fixture-only checks for non-mutating compatibility status (#94)."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from ragmark import index
from ragmark.config import RagmarkConfig
from ragmark.embed import FastembedEmbedder
from ragmark.model import Chunk, ModelIdentity
from ragmark.store import IndexStore

IDENTITY = ModelIdentity(name="fixture-model", dim=2, version="fixture-version")


def _snapshot(root: Path) -> dict:
    result = {}
    for path in (root, *sorted(root.rglob("*"))):
        stat = path.lstat()
        data = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        result[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size, data)
    return result


@pytest.fixture
def inspect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ragmark._compat_status import inspect_status

    def forbidden(*args, **kwargs):
        raise AssertionError("status attempted a mutating/model operation")

    def run(config, store, expected_identity=IDENTITY, *, actor_changes=frozenset()):
        before = _snapshot(tmp_path)
        with monkeypatch.context() as guarded:
            guarded.setattr(IndexStore, "connect", forbidden)
            guarded.setattr(index, "refresh", forbidden)
            guarded.setattr(index, "reindex", forbidden)
            for name in ("identity", "_load_model", "embed", "count_tokens"):
                guarded.setattr(FastembedEmbedder, name, forbidden)
            result = inspect_status(config, store, expected_identity)
        after = _snapshot(tmp_path)
        # Concurrent-writer fixtures explicitly declare only their own changed paths.
        assert {k: v for k, v in after.items() if k not in actor_changes} == {
            k: v for k, v in before.items() if k not in actor_changes
        }
        return result

    return run


def _built_index(tmp_path: Path, contents: dict[str, str]) -> tuple[RagmarkConfig, IndexStore]:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = RagmarkConfig.for_vault(vault)
    store = IndexStore(config.index_dir)
    conn = store.connect()
    store.write_identity(conn, IDENTITY)
    assignments = {}
    for row, (rel, text) in enumerate(contents.items()):
        note = vault / rel
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(text)
        store.write_note(
            conn, rel, hashlib.sha256(note.read_bytes()).hexdigest(), note.stat().st_mtime_ns
        )
        chunk = Chunk(rel + "#0", rel, 0, None, None, text, 1)
        store.replace_chunks(conn, rel, [chunk])
        assignments[chunk.chunk_id] = row
    store.assign_vector_rows(conn, assignments)
    conn.close()
    if contents:
        store.save_vectors(np.ones((len(contents), IDENTITY.dim), dtype=np.float32))
    return config, store


def test_missing_index_does_not_create_directory(tmp_path: Path, inspect) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = RagmarkConfig.for_vault(vault)

    result = inspect(config, IndexStore(config.index_dir))

    assert result["state"] == "missing"
    assert result["ready"] is False
    assert result["notes"] == 0
    assert result["chunks"] == 0
    assert result["stale_notes"] is None
    assert result["index_built_at"] is None
    assert result["root_provenance"] == "not_recorded"
    assert not config.index_dir.exists()


def test_healthy_index_reports_stored_counts_without_writes(tmp_path: Path, inspect) -> None:
    config, store = _built_index(tmp_path, {"brain/a.md": "unchanged"})

    result = inspect(config, store)

    assert result["state"] == "ready"
    assert result["ready"] is True
    assert result["notes"] == result["chunks"] == 1
    assert result["added_notes"] == result["changed_notes"] == result["deleted_notes"] == 0
    assert result["stale_notes"] == 0
    assert result["recorded_identity"] == {
        "name": IDENTITY.name,
        "dim": IDENTITY.dim,
        "version": IDENTITY.version,
    }
    assert result["index_built_at"] is None
    assert result["root_provenance"] == "not_recorded"


def test_status_rechecks_disk_even_when_store_has_cached_vectors(tmp_path: Path, inspect) -> None:
    config, store = _built_index(tmp_path, {"brain/a.md": "note"})
    store.load_vectors()  # Upstream #164 now caches by mtime and size.
    original_mtime = store.vectors_path.stat().st_mtime_ns
    original_size = store.vectors_path.stat().st_size
    np.save(store.vectors_path, np.full((1, 2), np.nan, dtype=np.float32))
    assert store.vectors_path.stat().st_size == original_size
    os.utime(store.vectors_path, ns=(original_mtime, original_mtime))

    result = inspect(config, store)

    assert result["state"] == "corrupt"
    assert result["ready"] is False


def test_staleness_counts_added_changed_deleted_without_refresh(tmp_path: Path, inspect) -> None:
    config, store = _built_index(
        tmp_path, {"brain/change.md": "old", "brain/delete.md": "remove", "brain/keep.md": "same"}
    )
    config = replace(config, excluded_dirs=frozenset({"templates"}))
    changed = config.vault_root / "brain/change.md"
    old_mtime = changed.stat().st_mtime_ns
    changed.write_text("new")
    os.utime(changed, ns=(old_mtime, old_mtime))
    (config.vault_root / "brain/delete.md").unlink()
    (config.vault_root / "brain/add.md").write_text("new note")
    for rel in ("templates/ignored.md", ".hidden/ignored.md", "brain/.ignored.md"):
        path = config.vault_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("outside configured static policy")

    result = inspect(config, store)

    assert result["state"] == "stale"
    assert result["ready"] is False
    assert result["notes"] == result["chunks"] == 3
    assert result["added_notes"] == result["changed_notes"] == result["deleted_notes"] == 1
    assert result["stale_notes"] == 3


@pytest.mark.parametrize(
    "other",
    [
        replace(IDENTITY, name="other-model"),
        replace(IDENTITY, dim=3),
        replace(IDENTITY, version="other-version"),
    ],
    ids=["name", "dimension", "version"],
)
def test_wrong_identity_is_reported_without_loading_model(tmp_path: Path, inspect, other) -> None:
    config, store = _built_index(tmp_path, {"brain/a.md": "note"})

    result = inspect(config, store, other)

    assert result["state"] == "identity_mismatch"
    assert result["ready"] is False
    assert "Rebuild" in result["error"]
    assert result["recorded_identity"]["name"] == IDENTITY.name


def test_schema_without_identity_is_unbuilt(tmp_path: Path, inspect) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = RagmarkConfig.for_vault(vault)
    store = IndexStore(config.index_dir)
    store.connect().close()

    result = inspect(config, store)

    assert result["state"] == "unbuilt"
    assert result["ready"] is False
    assert result["recorded_identity"] is None
    assert result["notes"] == result["chunks"] == 0


def test_empty_built_index_is_ready_without_vectors(tmp_path: Path, inspect) -> None:
    config, store = _built_index(tmp_path, {})

    result = inspect(config, store)

    assert result["state"] == "ready"
    assert result["ready"] is True
    assert result["notes"] == result["chunks"] == result["stale_notes"] == 0
    assert not store.vectors_path.exists()


@pytest.mark.parametrize(
    "damage",
    [
        "metadata-bytes",
        "missing-table",
        "wrong-schema",
        "partial-identity",
        "missing-vectors",
        "vector-bytes",
        "vector-rank",
        "vector-dimension",
        "vector-count",
        "duplicate-row",
        "out-of-range-row",
        "orphan-chunk",
        "nonfinite-vector",
        "nonnumeric-vector",
        "orphan-vectors",
        "vector-archive",
        "truncated-vector-archive",
    ],
)
def test_corrupt_artifacts_never_report_ready_or_repair(
    tmp_path: Path, inspect, damage: str
) -> None:
    config, store = _built_index(tmp_path, {"brain/a.md": "a", "brain/b.md": "b"})
    sql = {
        "missing-table": "DROP TABLE chunks",
        "wrong-schema": "UPDATE meta SET value='99' WHERE key='schema_version'",
        "partial-identity": "DELETE FROM meta WHERE key='model_version'",
        "duplicate-row": "UPDATE chunks SET vector_row=0",
        "out-of-range-row": "UPDATE chunks SET vector_row=10",
        "orphan-chunk": "UPDATE chunks SET note_path='brain/missing.md'",
    }
    if damage in sql:
        with sqlite3.connect(store.db_path) as conn:
            conn.execute(sql[damage])
        conn.close()
    elif damage == "metadata-bytes":
        store.db_path.write_bytes(b"not sqlite")
    elif damage == "missing-vectors":
        store.vectors_path.unlink()
    elif damage == "vector-bytes":
        store.vectors_path.write_bytes(b"not numpy")
    elif damage == "orphan-vectors":
        store.db_path.unlink()
    elif damage == "vector-archive":
        with store.vectors_path.open("wb") as handle:
            np.savez(handle, vectors=np.ones((2, 2)))
    elif damage == "truncated-vector-archive":
        store.vectors_path.write_bytes(b"PK\x03\x04not-a-complete-zip-file")
    else:
        matrices = {
            "vector-rank": np.ones(2),
            "vector-dimension": np.ones((2, 3)),
            "vector-count": np.ones((1, 2)),
            "nonfinite-vector": np.full((2, 2), np.nan),
            "nonnumeric-vector": np.full((2, 2), "not numbers"),
        }
        np.save(store.vectors_path, matrices[damage])

    result = inspect(config, store)

    assert result["state"] == "corrupt"
    assert result["ready"] is False
    assert result["notes"] is None
    assert result["chunks"] is None
    assert result["stale_notes"] is None
    assert result["error"]
    assert "--force" in result["remediation"]


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_sqlite_sidecars_refused_before_opening_database(
    tmp_path: Path, inspect, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    config, store = _built_index(tmp_path, {"brain/a.md": "note"})
    Path(str(store.db_path) + suffix).write_bytes(b"possibly active transaction")

    def forbidden(*args, **kwargs):
        raise AssertionError("status opened a database with an unsafe sidecar")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    result = inspect(config, store)

    assert result["state"] == "unavailable"
    assert result["ready"] is False
    assert result["notes"] is None
    assert "retry" in result["remediation"].lower()


@pytest.mark.parametrize("change", ["metadata", "vectors", "sidecar"])
def test_changing_index_snapshot_is_unavailable(
    tmp_path: Path, inspect, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    config, store = _built_index(tmp_path, {"brain/a.md": "note"})
    real_load = store.load_vectors
    target = {
        "metadata": store.db_path,
        "vectors": store.vectors_path,
        "sidecar": Path(str(store.db_path) + "-wal"),
    }[change]

    def concurrent_writer(_store):
        matrix = real_load()
        # Same content/mtime still changes inode (atomic replacement) or ctime.
        if change == "sidecar":
            target.write_bytes(b"new writer")
        else:
            old_time = target.stat().st_mtime_ns
            replacement = target.with_suffix(".replacement")
            replacement.write_bytes(target.read_bytes())
            os.utime(replacement, ns=(old_time, old_time))
            replacement.replace(target)
        return matrix

    monkeypatch.setattr(IndexStore, "load_vectors", concurrent_writer)
    result = inspect(
        config,
        store,
        actor_changes={str(target.relative_to(tmp_path)), str(target.parent.relative_to(tmp_path))},
    )

    assert result["state"] == "unavailable"
    assert result["ready"] is False
    assert result["stale_notes"] is None


@pytest.mark.parametrize("problem", ["missing-root", "store-mismatch"])
def test_unavailable_configuration_does_not_claim_empty_readiness(
    tmp_path: Path, inspect, problem: str
) -> None:
    config, store = _built_index(tmp_path, {})
    if problem == "missing-root":
        config = replace(config, vault_root=tmp_path / "missing")
    else:
        config = replace(config, index_dir=tmp_path / "other-index")

    result = inspect(config, store)

    assert result["state"] == "unavailable"
    assert result["ready"] is False


@pytest.mark.parametrize("change", ["added", "changed", "deleted"])
def test_changing_corpus_is_unavailable(
    tmp_path: Path, inspect, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    config, store = _built_index(tmp_path, {"brain/a.md": "note"})
    real_hash = hashlib.sha256
    note = config.vault_root / "brain/a.md"
    added = note.with_name("new.md")
    written = False

    def concurrent_writer(content):
        nonlocal written
        value = real_hash(content)
        if not written:
            written = True
            if change == "added":
                added.write_text("new")
            elif change == "changed":
                old_time = note.stat().st_mtime_ns
                note.write_text("edit")
                os.utime(note, ns=(old_time, old_time))
            else:
                note.unlink()
        return value

    monkeypatch.setattr(hashlib, "sha256", concurrent_writer)
    result = inspect(
        config,
        store,
        actor_changes={str(path.relative_to(tmp_path)) for path in (note, added, note.parent)},
    )

    assert result["state"] == "unavailable"
    assert result["ready"] is False
    assert result["stale_notes"] is None


def test_corpus_walk_errors_are_not_silently_reported_as_empty(
    tmp_path: Path, inspect, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, store = _built_index(tmp_path, {})

    def blocked_walk(root, *, onerror=None):
        if onerror:
            onerror(PermissionError("fixture directory unreadable"))
        return iter(())

    monkeypatch.setattr(os, "walk", blocked_walk)
    result = inspect(config, store)

    assert result["state"] == "unavailable"
    assert result["ready"] is False


def test_status_refuses_symlink_note_without_reading_target(
    tmp_path: Path, inspect, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, store = _built_index(tmp_path, {})
    external = tmp_path / "external.md"
    external.write_text("not part of vault")
    (config.vault_root / "alias.md").symlink_to(external)
    real_read = Path.read_bytes

    def refuse_symlink_read(path):
        if path.is_symlink():
            raise AssertionError("status read through a symlink")
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", refuse_symlink_read)
    result = inspect(config, store)

    assert result["state"] == "unavailable"
    assert result["ready"] is False


def test_database_open_is_read_only_and_immutable(
    tmp_path: Path, inspect, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, store = _built_index(tmp_path, {})
    real_connect = sqlite3.connect
    opened = []

    def checked_connect(database, **kwargs):
        assert database == store.db_path.resolve().as_uri() + "?mode=ro&immutable=1"
        assert kwargs == {"uri": True}
        opened.append(database)
        return real_connect(database, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", checked_connect)

    assert inspect(config, store)["ready"] is True
    assert len(opened) == 1


@pytest.mark.parametrize("artifact", ["db_path", "vectors_path"])
def test_nonregular_index_artifact_returns_without_blocking(tmp_path: Path, artifact: str) -> None:
    import json

    config, store = _built_index(tmp_path, {"brain/a.md": "note"})
    path = getattr(store, artifact)
    path.unlink()
    os.mkfifo(path)
    before = _snapshot(tmp_path)
    script = """
import json, sys
from pathlib import Path
from ragmark._compat_status import inspect_status
from ragmark.config import RagmarkConfig
from ragmark.model import ModelIdentity
from ragmark.store import IndexStore
config = RagmarkConfig.for_vault(Path(sys.argv[1]))
identity = ModelIdentity('fixture-model', 2, 'fixture-version')
print(json.dumps(inspect_status(config, IndexStore(config.index_dir), identity)))
"""
    # A blocking FIFO open must fail the test, never hang the test runner.
    child = subprocess.run(
        [sys.executable, "-B", "-c", script, str(config.vault_root)],
        check=True,
        capture_output=True,
        text=True,
        timeout=3,
    )
    result = json.loads(child.stdout)
    assert result["state"] == "unavailable"
    assert result["ready"] is False
    assert result["notes"] is None
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("operation", ["database", "vectors"])
def test_index_io_failure_is_unavailable_not_corrupt(
    tmp_path: Path, inspect, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    config, store = _built_index(tmp_path, {"brain/a.md": "note"})

    def denied(*args, **kwargs):
        raise PermissionError("fixture artifact is unreadable")

    if operation == "database":
        monkeypatch.setattr(sqlite3, "connect", denied)
    else:
        monkeypatch.setattr(IndexStore, "load_vectors", denied)

    result = inspect(config, store)

    assert result["state"] == "unavailable"
    assert result["ready"] is False
    assert "retry" in result["remediation"].lower()


@pytest.mark.parametrize(
    "code",
    [sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_PERM, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_IOERR_READ],
)
def test_sqlite_io_error_families_are_unavailable(
    tmp_path: Path, inspect, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    config, store = _built_index(tmp_path, {"brain/a.md": "note"})

    def denied(*args, **kwargs):
        error = sqlite3.OperationalError("fixture SQLite access failure")
        error.sqlite_errorcode = code
        raise error

    monkeypatch.setattr(sqlite3, "connect", denied)

    result = inspect(config, store)

    assert result["state"] == "unavailable"
    assert result["ready"] is False
    assert "retry" in result["remediation"].lower()


def test_real_unreadable_database_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    from ragmark._compat_status import inspect_status

    config, store = _built_index(tmp_path, {"brain/a.md": "note"})
    original = store.db_path.read_bytes()
    mode = store.db_path.stat().st_mode

    def forbidden(*args, **kwargs):
        raise AssertionError("status attempted a mutating/model operation")

    monkeypatch.setattr(IndexStore, "connect", forbidden)
    monkeypatch.setattr(index, "refresh", forbidden)
    monkeypatch.setattr(index, "reindex", forbidden)
    for name in ("identity", "_load_model", "embed", "count_tokens"):
        monkeypatch.setattr(FastembedEmbedder, name, forbidden)
    store.db_path.chmod(0)
    try:
        try:
            store.db_path.read_bytes()
        except PermissionError:
            pass
        else:
            pytest.skip("execution identity can read mode-000 files")
        before = store.db_path.stat()
        result = inspect_status(config, store, IDENTITY)
        after = store.db_path.stat()
        assert (before.st_mode, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        assert result["state"] == "unavailable"
        assert result["ready"] is False
        assert "retry" in result["remediation"].lower()
    finally:
        store.db_path.chmod(mode)
    assert store.db_path.read_bytes() == original
