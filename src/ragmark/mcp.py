"""The MCP face — four read-only tools over the core (decided on the-vault#142).

Prototyped live on the-vault branch `proto/ragmark-mcp-142` and accepted as-is:
tool names, argument shapes, return shapes, and the annotation set are the
contract — a change here is a decision, not a refactor.

Registration (decided): the server registers under the name **`vault`** so
existing `mcp__vault__*` tool names survive the cutover from the vendored
`vault_mcp.py`. The packaged entry point is `ragmark mcp --vault PATH`
(`RAGMARK_VAULT` env fallback); the vault root is never derived from
`__file__` — that trick dies with vendoring. The machine context is read
server-side from the vault root, never accepted from the caller.

Deliberate asymmetry: `ragmark index` is CLI-only. This face exposes no
maintenance operations — mtime-gated auto-refresh on the query path makes
staleness the server's problem, invisible to callers.

Writes stay out entirely (the containment rationale carried from
vault_mcp.py's header): an open write surface reachable by arbitrary agents
widens the prompt-injection surface. If writes are ever wanted they belong in
a single append-only capture tool routing through an inbox — never direct
note edits.

fastmcp imports lazily (the `mcp` extra) so the core stays importable and
testable without the server dependency.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ragmark import activity, gate, neighbors, search
from ragmark.config import RagmarkConfig
from ragmark.embed import FastembedEmbedder
from ragmark.store import IndexStore

# MCP behavior annotations, identical on every tool (basic-memory's steal,
# via the-vault#138): read-only, non-destructive, idempotent, closed-world.
READ_ONLY_ANNOTATIONS: dict[str, bool] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def build_server(config: RagmarkConfig) -> Any:
    """Build the FastMCP server exposing the read-only vault tools."""
    from fastmcp import FastMCP

    mcp: Any = FastMCP("ragmark")
    store = IndexStore(config.index_dir)
    embedder = FastembedEmbedder()

    @mcp.tool(annotations={"title": "Search the vault", **READ_ONLY_ANNOTATIONS})
    def vault_search(query: str, k: int = search.DEFAULT_RESULTS) -> list[dict]:
        """Hybrid (vector + lexical) search across the vault.

        Returns up to k context-visible hits, each
        {chunk_id, note_path, heading, score, snippet}. `chunk_id` is the
        citation handle: stable within an index build, resolvable to exact
        text. Queries auto-refresh the index; staleness is never the
        caller's problem.
        """
        hits = search.search(query, k, config=config, store=store, embedder=embedder)
        return [asdict(h) for h in hits]

    @mcp.tool(annotations={"title": "Read a vault note", **READ_ONLY_ANNOTATIONS})
    def vault_read(path: str) -> str:
        """Read one note by vault-relative path (e.g. 'reference/GraphRAG.md').

        Bare note text. One opaque error covers every failure mode — a
        probing caller learns only that the path is unavailable.
        """
        return gate.read_note(path, config)

    @mcp.tool(annotations={"title": "Walk a note's wikilink neighborhood", **READ_ONLY_ANNOTATIONS})
    def vault_neighbors(
        path: str,
        depth: int = neighbors.DEFAULT_DEPTH,
        token_budget: int = neighbors.DEFAULT_TOKEN_BUDGET,
    ) -> dict:
        """BFS over wikilinks (out-links AND backlinks) from one note.

        Structure is always complete; the token budget limits only how much
        content rides along — a tight budget degrades to a map of the
        neighborhood, never silence.
        """
        return asdict(neighbors.vault_neighbors(path, depth, token_budget, config=config))

    @mcp.tool(annotations={"title": "Recently changed notes", **READ_ONLY_ANNOTATIONS})
    def recent_activity(
        days: int = activity.DEFAULT_DAYS, limit: int = activity.DEFAULT_LIMIT
    ) -> list[dict]:
        """Context-visible notes changed in the last `days`, newest first.

        Each: {note_path, modified, first_line}. Git-log-backed; mtime
        fallback for non-repo vaults.
        """
        return [asdict(e) for e in activity.recent_activity(days, limit, config=config)]

    return mcp


def serve(config: RagmarkConfig) -> None:
    """Serve over stdio (the `ragmark mcp` entry point)."""
    build_server(config).run()
