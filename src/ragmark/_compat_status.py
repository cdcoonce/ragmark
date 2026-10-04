"""Private, non-mutating status support for the #94 compatibility adapter.

No CLI/MCP surface is added. This reports stored evidence, not model readiness
or proof of a vault/index association: the current store records neither vault
provenance nor a build timestamp.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from stat import S_ISREG
from zipfile import BadZipFile

from ragmark import gate
from ragmark.config import RagmarkConfig
from ragmark.model import ModelIdentity
from ragmark.store import SCHEMA_VERSION, IndexCorruptionError, IndexIdentityError, IndexStore


class _InspectionUnavailable(Exception):
    """The files cannot provide a stable read-only observation."""


def _fingerprint(path: Path) -> tuple | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    if not S_ISREG(stat.st_mode):
        raise _InspectionUnavailable("inspection requires regular file artifacts")
    return (
        str(path.resolve()),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _refuse_sidecars(store: IndexStore) -> None:
    for database in {store.db_path, store.db_path.resolve()}:
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(database) + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                raise _InspectionUnavailable("SQLite sidecar present; snapshot may be active")


def _failure(result: dict[str, object], state: str, error: str) -> dict[str, object]:
    result.update(
        state=state,
        ready=False,
        error=error,
        notes=None,
        chunks=None,
        stale_notes=None,
        added_notes=None,
        changed_notes=None,
        deleted_notes=None,
        remediation=(
            "Retry when the configured files are accessible and writers are idle."
            if state == "unavailable"
            else "ragmark index --force"
        ),
    )
    return result


def _validate_vectors(store: IndexStore, identity: ModelIdentity, notes: dict, rows: list) -> None:
    import numpy as np

    # A caller may retain a #164 store cache keyed only by mtime/size. Status
    # verifies the current artifact, including same-key out-of-band rewrites;
    # use a fresh public reader without touching the caller's cache internals.
    matrix = IndexStore(store.index_dir).load_vectors()
    if matrix is None:
        if rows:
            raise IndexCorruptionError("index vectors are missing")
        return
    if isinstance(matrix, np.lib.npyio.NpzFile):
        matrix.close()
        raise IndexCorruptionError("vectors must be one NumPy array, not an archive")
    if matrix.ndim != 2 or matrix.shape != (len(rows), identity.dim):
        raise IndexCorruptionError("vector shape disagrees with chunk count or model dimension")
    if not np.issubdtype(matrix.dtype, np.floating) or not np.isfinite(matrix).all():
        raise IndexCorruptionError("vectors are not finite floating-point values")
    positions = [row[-1] for row in rows]
    if sorted(positions) != list(range(len(rows))):
        raise IndexCorruptionError("chunk vector references are not a dense one-to-one mapping")
    if any(row[1] not in notes for row in rows):
        raise IndexCorruptionError("a chunk references an unrecorded note")


def _corpus_snapshot(config: RagmarkConfig) -> dict[str, tuple]:
    def walk_error(error: OSError) -> None:
        raise error

    snapshot = {}
    for directory, dirs, files in os.walk(config.vault_root, onerror=walk_error):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in config.excluded_dirs]
        for name in files:
            path = Path(directory) / name
            if gate.is_indexable_note(path, config):
                if path.is_symlink() or not path.is_file():
                    raise _InspectionUnavailable("corpus contains a symlink or non-regular note")
                rel = path.relative_to(config.vault_root).as_posix()
                fingerprint = _fingerprint(path)
                if fingerprint is None:
                    raise _InspectionUnavailable("corpus changed during inspection")
                snapshot[rel] = fingerprint
    return snapshot


def _live_hashes(config: RagmarkConfig) -> dict[str, str]:
    before = _corpus_snapshot(config)
    hashes = {
        rel: hashlib.sha256((config.vault_root / rel).read_bytes()).hexdigest() for rel in before
    }
    if before != _corpus_snapshot(config):
        raise _InspectionUnavailable("corpus changed during inspection")
    return hashes


def inspect_status(
    config: RagmarkConfig, store: IndexStore, expected_identity: ModelIdentity
) -> dict[str, object]:
    """Inspect a configured index without creating or repairing any artifact."""
    result: dict[str, object] = {
        "vault_root": str(config.vault_root.resolve()),
        "index_dir": str(store.index_dir.resolve()),
        "model": expected_identity.name,
        "recorded_identity": None,
        "notes": 0,
        "chunks": 0,
        "stale_notes": None,
        "added_notes": None,
        "changed_notes": None,
        "deleted_notes": None,
        "index_built_at": None,
        "root_provenance": "not_recorded",
        "ready": False,
        "state": "missing",
    }
    try:
        if not config.vault_root.is_dir():
            raise _InspectionUnavailable("configured vault root is not an accessible directory")
        if config.index_dir.resolve() != store.index_dir.resolve():
            raise _InspectionUnavailable("store directory differs from configured index directory")
        _refuse_sidecars(store)
        before = (_fingerprint(store.db_path), _fingerprint(store.vectors_path))
        result = _inspect_index(config, store, expected_identity, result)
        _refuse_sidecars(store)
        after = (_fingerprint(store.db_path), _fingerprint(store.vectors_path))
        if before != after:
            raise _InspectionUnavailable("index artifacts changed during inspection")
        return result
    except (_InspectionUnavailable, OSError) as exc:
        return _failure(result, "unavailable", str(exc))


def _inspect_index(
    config: RagmarkConfig,
    store: IndexStore,
    expected_identity: ModelIdentity,
    result: dict[str, object],
) -> dict[str, object]:
    if not store.db_path.exists():
        if store.vectors_path.exists():
            return _failure(result, "corrupt", "vectors exist without metadata")
        return result
    uri = store.db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.execute("PRAGMA query_only = ON")
            if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise IndexCorruptionError("metadata integrity check failed")
            schema = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if schema != (str(SCHEMA_VERSION),):
                raise IndexCorruptionError("metadata schema version is missing or unsupported")
            identity = store.read_identity(conn)
            notes = store.read_notes(conn)
            rows = store.read_chunk_rows(conn)
            if identity is None:
                identity_fields = conn.execute(
                    "SELECT COUNT(*) FROM meta WHERE key IN "
                    "('model_name', 'model_dim', 'model_version')"
                ).fetchone()[0]
                if identity_fields or notes or rows or store.vectors_path.exists():
                    raise IndexCorruptionError("built artifacts lack a complete model identity")
                result["state"] = "unbuilt"
                return result
            if not identity.name or identity.dim <= 0 or not identity.version:
                raise IndexCorruptionError("model identity is invalid")
            result["recorded_identity"] = asdict(identity)
            store.check_identity(conn, expected_identity)
            chunks = store.chunk_count(conn)
            if chunks != len(rows):
                raise IndexCorruptionError("metadata chunk counts disagree")
            _validate_vectors(store, identity, notes, rows)
    except IndexIdentityError as exc:
        return _failure(result, "identity_mismatch", str(exc))
    except sqlite3.DatabaseError as exc:
        # SQLite translates OS access failures into its own exception family.
        # Mask extended codes (e.g. IOERR_READ) to the primary result code.
        code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        inaccessible = code in {sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_PERM, sqlite3.SQLITE_IOERR}
        return _failure(
            result,
            "unavailable" if inaccessible else "corrupt",
            f"index cannot be verified: {exc}",
        )
    except (
        IndexCorruptionError,
        ValueError,
        TypeError,
        EOFError,
        BadZipFile,
    ) as exc:
        return _failure(result, "corrupt", f"index cannot be verified: {exc}")
    live = _live_hashes(config)
    added = len(live.keys() - notes.keys())
    changed = sum(live[path] != notes[path][0] for path in live.keys() & notes.keys())
    deleted = len(notes.keys() - live.keys())
    stale = added + changed + deleted
    result.update(
        recorded_identity=asdict(identity),
        notes=len(notes),
        chunks=chunks,
        added_notes=added,
        changed_notes=changed,
        deleted_notes=deleted,
        stale_notes=stale,
        state="stale" if stale else "ready",
        ready=not stale,
    )
    return result
