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

import graphmark

from ragmark import gate
from ragmark.config import RagmarkConfig
from ragmark.model import Neighbor, Neighborhood

DEFAULT_DEPTH = 1
MAX_DEPTH = 3
DEFAULT_TOKEN_BUDGET = 4000

_DIRECTION_RANK = {"out": 0, "back": 1}


def vault_neighbors(
    path: str,
    depth: int = DEFAULT_DEPTH,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    *,
    config: RagmarkConfig,
) -> Neighborhood:
    """Walk the wikilink neighborhood of *path* (see module contract)."""
    gate.resolve_note(path, config)  # propagate on the origin itself (cli.py already maps it)
    depth = min(depth, MAX_DEPTH)

    graph = graphmark.build(config.vault_root)
    visited = {path}
    assigned: dict[str, tuple[int, str, str]] = {}
    frontier = [path]
    level = 0
    while frontier and level < depth:
        level += 1
        candidates: list[tuple[str, str, str]] = []
        for direction in ("out", "back"):
            links = graph.out_links if direction == "out" else graph.back_links
            for node in frontier:
                for target in sorted(links.get(node, ())):
                    candidates.append((target, node, direction))
        next_frontier: list[str] = []
        for target, via, direction in candidates:
            if target in visited:
                continue
            visited.add(target)
            # Fail closed at DISCOVERY, not at emission: a gated note is neither
            # named nor walked through, so it can never surface as the `via` of
            # something further out. Gating that only filtered the emitted list
            # would still print a hidden note's path (and the fact that it links
            # onward) — exactly the leak gate.py's one-opaque-error property and
            # the "context gating never leaks" invariant exist to prevent.
            try:
                gate.resolve_note(target, config)
            except gate.VaultAccessError:
                continue
            assigned[target] = (level, via, direction)
            next_frontier.append(target)
        frontier = next_frontier

    ordered = sorted(
        assigned.items(), key=lambda item: (item[1][0], _DIRECTION_RANK[item[1][2]], item[0])
    )

    neighbors: list[Neighbor] = []
    budget_left = token_budget
    starved = False
    for note_path, (note_depth, via, direction) in ordered:
        text = gate.read_note(note_path, config)
        tokens = len(text.split())
        included = False
        content = None
        if not starved and tokens <= budget_left:
            included = True
            content = text
            budget_left -= tokens
        else:
            starved = True
        neighbors.append(
            Neighbor(
                note_path=note_path,
                depth=note_depth,
                via=via,
                direction=direction,
                tokens=tokens,
                included=included,
                content=content,
            )
        )

    return Neighborhood(
        origin=path, context=gate.active_context(config), neighbors=tuple(neighbors)
    )
