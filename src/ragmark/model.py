"""Public data shapes — the decided contract, seeded.

These types are the seam every surface (library, CLI, MCP) speaks. The shapes
were decided on the blueprint map and are not the executor's to redesign:
`chunk_id` is the mechanically-verifiable citation handle (the-vault#141/#142),
`Neighbor.included` carries the budget-degradation contract (the-vault#142),
and `ModelIdentity` is what makes a model swap a detected error instead of a
silent shape-crash (the-vault#140).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """Embedding model identity, recorded in the index and checked on open."""

    name: str
    dim: int
    version: str


@dataclass(frozen=True, slots=True)
class NoteMeta:
    """Frontmatter surface the index cares about (parsed as real YAML)."""

    description: str | None
    tags: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Chunk:
    """One embeddable unit of a note.

    `chunk_id` is `f"{note_path}#{chunk_index}"` — stable within one index
    build, resolvable back to exact text; it is the handle citations bind to.
    `parent_ref` names the enclosing heading section so retrieval can expand a
    small hit to its parent (retrieve-small / expand-to-parent).
    """

    chunk_id: str
    note_path: str
    chunk_index: int
    heading: str | None
    parent_ref: str | None
    text: str
    token_count: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One context-visible retrieval hit."""

    chunk_id: str
    note_path: str
    heading: str | None
    score: float
    snippet: str


@dataclass(frozen=True, slots=True)
class Neighbor:
    """One note in a wikilink neighborhood walk.

    Structure is always complete: a neighbor appears even when the token
    budget is spent — `included` is False and `content` is None, so a starved
    call degrades to a map of the neighborhood, never to silence.
    """

    note_path: str
    depth: int
    via: str
    direction: str  # "out" | "back"
    tokens: int
    included: bool
    content: str | None


@dataclass(frozen=True, slots=True)
class Neighborhood:
    """Result of a `vault_neighbors` walk."""

    origin: str
    context: str
    neighbors: tuple[Neighbor, ...]


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    """One recently-changed note (git-log-backed; mtime fallback)."""

    note_path: str
    modified: str  # ISO-8601
    first_line: str
