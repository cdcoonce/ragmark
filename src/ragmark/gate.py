"""Machine-context gating and the note access boundary — implemented in the seed.

This is the security core every surface routes through (the-vault#140,
decision 8: gating lives in core so CLI, MCP, and library calls gate
identically — the /find-vs-MCP asymmetry the survey found becomes structurally
impossible). It migrates from the vault's `vault_mcp.py`, where the design
carried three deliberate properties, all preserved here:

- **Fail closed.** An unknown context sees shared notes only: the moment we
  are least sure where we are running is the moment to reveal least.
- **Server-side context.** The context is read from the vault root, never
  accepted from the caller — a work machine that could ask for "personal"
  would defeat the boundary.
- **One opaque error.** "Outside the vault", "not a note", "missing", and
  "out of context" are indistinguishable to the caller: a probe learns only
  that a path is unavailable, never the shape of the filesystem behind it —
  nor whether a note it may not see exists at all.

The gating test suite for this module is teeth-checked (the-vault#144):
`scripts/teeth_check.py` re-runs it with the filter defanged and requires red.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from ragmark.config import CONTEXT_FILE, RagmarkConfig

_UNAVAILABLE = "path is not available: {rel_path}"


class VaultAccessError(Exception):
    """Raised when a requested path is not a readable, in-context vault note."""


def note_context(rel_path: str, config: RagmarkConfig) -> str | None:
    """Return the machine context owning *rel_path*, or None when shared."""
    parts = PurePosixPath(rel_path).parts
    if not parts:
        return None
    return config.context_dirs.get(parts[0])


def visible_in_context(rel_path: str, context: str, config: RagmarkConfig) -> bool:
    """True when a note at *rel_path* may surface on a *context* machine."""
    owner = note_context(rel_path, config)
    if owner is None:
        return True
    return owner in config.visible_scopes.get(context, frozenset())


def active_context(config: RagmarkConfig) -> str:
    """Read the machine context from the vault root; "unknown" when unmarked.

    Server-side by construction: never a caller parameter.
    """
    marker = config.vault_root / CONTEXT_FILE
    if not marker.exists():
        return "unknown"
    context = marker.read_text(encoding="utf-8").strip()
    if not context:
        return "unknown"
    return context


def is_indexable_note(resolved: Path, config: RagmarkConfig) -> bool:
    """True when *resolved* (inside the vault) is graph content.

    Markdown only; hidden paths and configured exclusions stay unreachable.
    Optional owner scope is applied before indexing or exposing stored results
    (ragmark#94, owner decision 2026-10-03).
    """
    if resolved.suffix.lower() != ".md":
        return False
    rel = resolved.relative_to(config.vault_root)
    rel_parts = rel.parts
    if config.scoped_folders and (len(rel_parts) < 2 or rel_parts[0] not in config.scoped_folders):
        return False
    if rel_parts[-1] in config.excluded_filenames:
        return False
    if rel.as_posix().startswith(config.excluded_path_prefixes):
        return False
    for part in rel_parts[:-1]:
        if part.startswith(".") or part in config.excluded_dirs:
            return False
    return not rel_parts[-1].startswith(".")


def _has_exact_spelling(root: Path, relative: Path) -> bool:
    """Refuse filesystem aliases without changing literal owner policy.

    On case-insensitive filesystems resolve() can retain the caller's casing.
    Check directory entries rather than folding configured names: a real
    `agents.md` must still be distinct from the excluded literal `AGENTS.md`.
    """
    current = root
    try:
        for part in relative.parts:
            if part == "..":
                current = current.parent
                continue
            if not any(entry.name == part for entry in current.iterdir()):
                return False
            current /= part
    except OSError:
        return False
    return True


def resolve_note(rel_path: str, config: RagmarkConfig) -> Path:
    """Resolve *rel_path* to a readable, in-context note inside the vault.

    The order matters and is load-bearing: `resolve()` runs FIRST so symlinks
    and `..` segments are collapsed before the containment check — a check
    against the unresolved path passes for a symlink pointing out of the
    vault, which is precisely the exfiltration case. Only then is the result
    tested for being indexable content and for context visibility.

    Every reader routes through here so there is exactly one implementation
    of the access boundary to get right.
    """
    # Absolute inputs are refused outright: the API contract is vault-relative
    # paths, and `root / rel_path` would silently honor an absolute path that
    # happens to point inside the vault. (The predecessor's comment claimed
    # containment caught this; it only caught absolute paths pointing OUT.)
    if Path(rel_path).is_absolute():
        raise VaultAccessError(_UNAVAILABLE.format(rel_path=rel_path))

    root = config.vault_root.resolve()
    resolved = (root / rel_path).resolve()

    if not resolved.is_relative_to(root):
        raise VaultAccessError(_UNAVAILABLE.format(rel_path=rel_path))
    if not resolved.is_file():
        raise VaultAccessError(_UNAVAILABLE.format(rel_path=rel_path))
    if not _has_exact_spelling(root, Path(rel_path)) or not _has_exact_spelling(
        root, resolved.relative_to(root)
    ):
        raise VaultAccessError(_UNAVAILABLE.format(rel_path=rel_path))
    if not is_indexable_note(root / rel_path, config):
        raise VaultAccessError(_UNAVAILABLE.format(rel_path=rel_path))
    if not is_indexable_note(resolved, config):
        raise VaultAccessError(_UNAVAILABLE.format(rel_path=rel_path))
    rel = resolved.relative_to(root).as_posix()
    context = active_context(config)
    # A stored personal path remains private even if it now aliases shared
    # content; a shared alias must likewise never expose a private target.
    if not visible_in_context(rel_path, context, config) or not visible_in_context(
        rel, context, config
    ):
        raise VaultAccessError(_UNAVAILABLE.format(rel_path=rel_path))
    return resolved


def read_note(rel_path: str, config: RagmarkConfig) -> str:
    """Return the bare text of one vault note (the decided `vault_read` shape)."""
    return resolve_note(rel_path, config).read_text(encoding="utf-8")


def filter_visible(rel_paths: list[str], config: RagmarkConfig) -> list[str]:
    """Keep readable corpus paths visible in the active context, in order.

    Stored rows may predate a corpus-policy change; filter them through the
    same resolve/contain/scope boundary as direct reads before exposing them.
    """
    visible: list[str] = []
    for path in rel_paths:
        try:
            resolve_note(path, config)
        except VaultAccessError:
            continue
        visible.append(path)
    return visible
