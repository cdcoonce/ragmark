"""Configuration — the domain seam.

Everything vault-specific is config: which top-level directories are indexed,
which machine contexts exist and what each may see, where the derived index
lives. The engine modules never hard-code a vault layout; `configs/the-vault.toml`
in this repo is the reference instance (graphmark's `configs/my-brain.toml`
pattern).

The context maps default to the reference vault's policy because that policy is
load-bearing prior art (migrated from the vault's `vault_mcp.py`): the work
context is the restricted one, and an unknown context sees shared notes only —
fail-closed in the one place that must fail closed.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Machine context that owns a top-level directory. Directories absent from the
# map (brain/, reference/, thinking/, school/ in the reference vault) are shared.
# `school/` shared is a deliberate recorded decision, not an omission
# (the-vault#140, decision 9).
DEFAULT_CONTEXT_DIRS: dict[str, str] = {"work": "work", "personal": "personal"}

# Which owned scopes each machine context may see. Deliberately ASYMMETRIC: the
# vault is one repo synced to both machines, so hiding work/ from the personal
# machine protects nothing; personal material surfacing on an employer-managed
# machine is the exposure that matters. A context absent from this map
# (notably "unknown") sees shared notes only.
DEFAULT_VISIBLE_SCOPES: dict[str, frozenset[str]] = {
    "personal": frozenset({"personal", "work"}),
    "work": frozenset({"work"}),
}

# File at the vault root naming the machine context. Read server-side by
# construction — the caller never supplies the context.
CONTEXT_FILE = ".vault-context"


@dataclass(frozen=True, slots=True)
class RagmarkConfig:
    """Resolved configuration for one vault.

    `index_dir` holds the derived layer (vectors + SQLite metadata). It is
    machine-local and regenerable; nothing under it is ever committed.
    """

    vault_root: Path
    index_dir: Path
    excluded_dirs: frozenset[str] = frozenset()
    context_dirs: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CONTEXT_DIRS))
    visible_scopes: dict[str, frozenset[str]] = field(
        default_factory=lambda: dict(DEFAULT_VISIBLE_SCOPES)
    )

    @classmethod
    def for_vault(cls, vault_root: Path, index_dir: Path | None = None) -> RagmarkConfig:
        """Default configuration rooted at *vault_root*."""
        root = vault_root.resolve() if vault_root.exists() else vault_root
        return cls(
            vault_root=root,
            index_dir=root / ".ragmark" if index_dir is None else index_dir,
        )

    @classmethod
    def from_toml(cls, path: Path) -> RagmarkConfig:
        """Load a config file (see `configs/the-vault.toml` for the shape).

        Paths in the file are resolved relative to the file's directory, so a
        config checked into a vault keeps working from any working directory.
        """
        if not path.exists():
            raise FileNotFoundError(f"config not found: {path}")
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        base = path.parent

        vault_root = (base / data["vault_root"]).resolve()
        index_dir = (
            (base / data["index_dir"]).resolve() if "index_dir" in data else vault_root / ".ragmark"
        )
        scopes = {
            context: frozenset(owned)
            for context, owned in data.get("visible_scopes", DEFAULT_VISIBLE_SCOPES).items()
        }
        return cls(
            vault_root=vault_root,
            index_dir=index_dir,
            excluded_dirs=frozenset(data.get("excluded_dirs", ())),
            context_dirs=dict(data.get("context_dirs", DEFAULT_CONTEXT_DIRS)),
            visible_scopes=scopes,
        )
