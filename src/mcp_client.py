"""
MCP Client singleton for in-process tool calls.

Provides tool_call() helper that routes through the FastMCP Client
using in-memory transport, so the orchestrator talks to mcp_server.py
via the MCP protocol instead of direct Python imports.

Usage:
    from src.mcp_client import init_mcp_client, close_mcp_client, tool_call

    await init_mcp_client()
    chunks = await tool_call("mcp_search_chunks", query="RAG", top_k=10)
    await close_mcp_client()
"""

import json
import logging
from contextlib import AsyncExitStack
from typing import Any

from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import TextContent

from src.mcp_server import mcp

logger = logging.getLogger(__name__)

_client: Client | None = None
_stack: AsyncExitStack = AsyncExitStack()


class MCPToolError(Exception):
    """Raised when an MCP tool call fails."""

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"MCP tool '{tool_name}' failed: {message}")


async def init_mcp_client() -> None:
    """Initialize the MCP client with in-memory transport to mcp_server."""
    global _client
    if _client is not None:
        return
    _client = await _stack.enter_async_context(Client(mcp))


async def close_mcp_client() -> None:
    """Shut down the MCP client and release resources."""
    global _client, _stack
    await _stack.aclose()
    _client = None
    _stack = AsyncExitStack()


def _to_plain(obj: Any) -> Any:
    """Recursively convert Pydantic models / dataclasses to plain dicts/lists."""
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


def _extract_data(result) -> Any:
    """Extract typed data from a CallToolResult as plain Python objects.

    FastMCP's structured output may deserialize list[dict] into Pydantic
    Root models.  We normalise everything back to plain dicts/lists so the
    rest of the codebase can use standard dict access (.get(), [] etc.).

    Priority: TextContent JSON > .data (with model_dump fallback).
    """
    if result.content:
        first = result.content[0]
        if isinstance(first, TextContent):
            try:
                return json.loads(first.text)
            except (json.JSONDecodeError, TypeError):
                return first.text

    if result.data is not None:
        return _to_plain(result.data)

    return None


async def tool_call(name: str, **kwargs: Any) -> Any:
    """
    Call an MCP tool by name and return its unwrapped result.

    Args:
        name: The MCP tool name (e.g. "mcp_search_chunks").
        **kwargs: Tool arguments forwarded as-is.

    Returns:
        The tool's return value (dict, list, str, or None).

    Raises:
        MCPToolError: If the tool reports an error.
        RuntimeError: If the client has not been initialized.
    """
    if _client is None:
        raise RuntimeError(
            "MCP client not initialized. Call init_mcp_client() first."
        )
    try:
        result = await _client.call_tool(name, kwargs)
        data = _extract_data(result)
        if data is None and result.content:
            logger.warning(
                "tool_call(%s): .data was None, content=%s",
                name,
                [type(c).__name__ for c in result.content],
            )
        return data
    except ToolError as e:
        raise MCPToolError(name, str(e)) from e
