"""
Dispatch-style mock for src.orchestrator.tool_call.

After Phase 3, the orchestrator calls tool_call("mcp_search_chunks", ...)
instead of search_chunks(...). Tests need a single mock that dispatches
by tool name to return the right fixture data.
"""

from typing import Any, Callable


class _Seq:
    """Marker for sequential return values in make_tool_mock."""

    def __init__(self, items: list):
        self.items = list(items)


def seq(*items: Any) -> _Seq:
    """Wrap values to be returned one per call (pop-from-front).

    Use for tools called multiple times that should return different values::

        "mcp_pick_next_intent": seq("problem", None),
        "mcp_validate_slide_structure": seq(
            {"is_valid": False, "errors": ["too long"]},
            {"is_valid": True, "errors": []},
        ),

    Plain values (including lists) are returned as-is every time.
    """
    return _Seq(list(items))


def make_tool_mock(responses: dict[str, Any]) -> Callable:
    """Create an async side_effect that dispatches by tool name.

    Usage::

        responses = {
            "mcp_search_chunks": [chunk1, chunk2],      # list returned as-is
            "mcp_pick_next_intent": seq("problem", None), # sequential returns
            "mcp_commit_slide": {"slide_id": "..."},     # dict returned as-is
        }
        with patch("src.orchestrator.tool_call", side_effect=make_tool_mock(responses)):
            ...

    Values can be:
      - A plain value including lists (returned as-is on every call)
      - A callable (called with **kwargs and its return value used)
      - A ``seq(...)`` (popped from front on each call)

    Raises ValueError for unmocked tool names to catch missing test setup.
    """

    async def _dispatch(name: str, **kwargs: Any) -> Any:
        if name not in responses:
            raise ValueError(f"Unmocked tool call: {name}({kwargs})")
        val = responses[name]
        if isinstance(val, _Seq):
            if not val.items:
                raise ValueError(f"Exhausted side_effect sequence for {name}")
            item = val.items.pop(0)
            return item() if callable(item) else item
        return val() if callable(val) else val

    return _dispatch
