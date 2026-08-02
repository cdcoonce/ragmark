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

    Markdown only; nothing under a dot-directory (`.claude/`, `.git/`,
    `.ragmark/` stay unreachable); nothing under an excluded directory.
    """
    if resolved.suffix.lower() != ".md":
        return False
    rel_parts = resolved.relative_to(config.vault_root).parts
    for part in rel_parts[:-1]:
        if part.startswith(".") or part in config.excluded_dirs:
            return False
    return not rel_parts[-1].startswith(".")


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
    if not is_indexable_note(resolved, config):
        raise VaultAccessError(_UNAVAILABLE.format(rel_path=rel_path))
    rel = resolved.relative_to(root).as_posix()
    if not visible_in_context(rel, active_context(config), config):
        raise VaultAccessError(_UNAVAILABLE.format(rel_path=rel_path))
    return resolved


def read_note(rel_path: str, config: RagmarkConfig) -> str:
    """Return the bare text of one vault note (the decided `vault_read` shape)."""
    return resolve_note(rel_path, config).read_text(encoding="utf-8")


def filter_visible(rel_paths: list[str], config: RagmarkConfig) -> list[str]:
    """Keep only the paths visible in the active context, preserving order."""
    context = active_context(config)
    return [p for p in rel_paths if visible_in_context(p, context, config)]
