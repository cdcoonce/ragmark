"""Wikilink neighborhood walks — graph-awareness as an explicit surface.

The decided shape (the-vault#142, accepted live): BFS over wikilinks from one
note, out-links AND backlinks first-class; the STRUCTURE is always complete
within `depth`, and `token_budget` limits only how much content rides along —
a starved call degrades to a map of the neighborhood, never to silence.

Graph reads come from **graphmark** (the dependency decided on the-vault#139;
its 2026-07-19 identity is reaffirmed — no embeddings, no retrieval surface
there). This module builds the deterministic graph via graphmark and applies
ragmark's context gate to every neighbor before it surfaces.
"""

from __future__ import annotations

from ragmark.config import RagmarkConfig
from ragmark.model import Neighborhood

DEFAULT_DEPTH = 1
MAX_DEPTH = 3
DEFAULT_TOKEN_BUDGET = 4000


def vault_neighbors(
    path: str,
    depth: int = DEFAULT_DEPTH,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    *,
    config: RagmarkConfig,
) -> Neighborhood:
    """Walk the wikilink neighborhood of *path* (see module contract)."""
    raise NotImplementedError("build slice: graphmark-backed neighbors (the-vault#142)")
