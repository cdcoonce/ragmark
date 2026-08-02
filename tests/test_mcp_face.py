"""The MCP face contract — names, arg shapes, annotations, and the gate.

Pins the surface decided on the-vault#142 (accepted live on the prototype).
A tool rename, a changed argument, or a dropped annotation goes red here:
the face is a decision, not an implementation detail.
"""

from __future__ import annotations

import asyncio

import pytest

from ragmark import mcp as ragmark_mcp

fastmcp = pytest.importorskip("fastmcp")

EXPECTED_ARGS = {
    "vault_search": {"query", "k"},
    "vault_read": {"path"},
    "vault_neighbors": {"path", "depth", "token_budget"},
    "recent_activity": {"days", "limit"},
}


def list_tools(config) -> list:
    async def go() -> list:
        async with fastmcp.Client(ragmark_mcp.build_server(config)) as client:
            return await client.list_tools()

    return asyncio.run(go())


def test_face_names_args_and_annotations(make_vault) -> None:
    tools = {t.name: t for t in list_tools(make_vault("personal"))}
    assert set(tools) == set(EXPECTED_ARGS)

    for name, tool in tools.items():
        assert set(tool.inputSchema.get("properties", {})) == EXPECTED_ARGS[name], name
        annotations = tool.annotations
        assert annotations is not None, name
        assert annotations.readOnlyHint is True, name
        assert annotations.destructiveHint is False, name
        assert annotations.idempotentHint is True, name
        assert annotations.openWorldHint is False, name


def test_vault_read_serves_in_context_note(make_vault) -> None:
    config = make_vault("personal")

    async def go() -> str:
        async with fastmcp.Client(ragmark_mcp.build_server(config)) as client:
            result = await client.call_tool(
                "vault_read", {"path": "personal/projects/side-project.md"}
            )
            return result.structured_content["result"]

    assert "Personal-scope note" in asyncio.run(go())


@pytest.mark.gating
def test_vault_read_refuses_across_the_boundary(make_vault) -> None:
    """The face-level leak test: the gate holds through the MCP surface."""
    config = make_vault("work")

    async def go() -> None:
        async with fastmcp.Client(ragmark_mcp.build_server(config)) as client:
            await client.call_tool("vault_read", {"path": "personal/projects/side-project.md"})

    with pytest.raises(Exception, match="not available"):
        asyncio.run(go())
