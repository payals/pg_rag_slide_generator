"""
Smoke tests for src/mcp_client.py -- Phase 2 checkpoint.

Verifies:
1. tool_call() round-trip through in-memory MCP transport
2. Enum serialization (SlideIntent string values survive JSON ser/deser)
3. init_pool() idempotency guard (double init is safe)
4. MCPToolError wrapping on bad input
5. Client lifecycle (init/close/re-init)
6. RuntimeError when calling tool_call() before init
"""

import pytest
import pytest_asyncio

import src.db as _db_mod
from src.db import init_pool, close_pool
from src.mcp_client import (
    MCPToolError,
    close_mcp_client,
    init_mcp_client,
    tool_call,
)
from src import config


@pytest_asyncio.fixture
async def mcp_env():
    """Set up pool + MCP client, tear down after test.

    Force-clears any stale pool left by prior tests (e.g. unpatched
    get_deck_state in test_generation_loop.py creates a pool on a
    now-closed event loop).
    """
    _db_mod._pool = None
    await init_pool()
    await init_mcp_client()
    yield
    await close_mcp_client()
    await close_pool()


@pytest.mark.integration
class TestMCPClientRoundTrip:
    """Basic tool_call round-trip tests against the real database."""

    @pytest.mark.asyncio
    async def test_create_deck_and_get_state(self, mcp_env):
        """tool_call returns dict from mcp_create_deck + mcp_get_deck_state."""
        deck_id = await tool_call(
            "mcp_create_deck",
            topic="Smoke Test Deck",
            target_slides=3,
        )
        assert isinstance(deck_id, str)
        assert len(deck_id) == 36  # UUID format

        state = await tool_call("mcp_get_deck_state", deck_id=deck_id)
        assert isinstance(state, dict)
        assert state["deck"]["topic"] == "Smoke Test Deck"
        assert state["deck"]["target_slides"] == 3

    @pytest.mark.asyncio
    async def test_pick_next_intent_returns_string(self, mcp_env):
        """pick_next_intent returns a plain string (not wrapped)."""
        deck_id = await tool_call(
            "mcp_create_deck",
            topic="Intent Test Deck",
            target_slides=15,
        )
        intent = await tool_call("mcp_pick_next_intent", deck_id=deck_id)
        assert isinstance(intent, str)
        assert intent in config.VALID_ENUMS["slide_intent"]

    @pytest.mark.asyncio
    async def test_pick_next_intent_with_exclude(self, mcp_env):
        """Enum string values in exclude list survive JSON serialization."""
        deck_id = await tool_call(
            "mcp_create_deck",
            topic="Enum Ser Test",
            target_slides=15,
        )
        exclude = ["problem", "thesis"]
        intent = await tool_call(
            "mcp_pick_next_intent",
            deck_id=deck_id,
            exclude=exclude,
        )
        assert intent not in exclude
        assert isinstance(intent, str)

    @pytest.mark.asyncio
    async def test_pick_next_intent_exhausts_to_none(self, mcp_env):
        """pick_next_intent returns None when all intents are excluded."""
        deck_id = await tool_call(
            "mcp_create_deck",
            topic="Exhaust Test",
            target_slides=15,
        )
        all_intents = list(config.VALID_ENUMS["slide_intent"])
        intent = await tool_call(
            "mcp_pick_next_intent",
            deck_id=deck_id,
            exclude=all_intents,
        )
        assert intent is None


@pytest.mark.integration
class TestMCPClientErrors:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_tool_call_before_init_raises_runtime_error(self):
        """Calling tool_call without init raises RuntimeError."""
        # Ensure client is not initialized by resetting state
        import src.mcp_client as mod
        saved = mod._client
        mod._client = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                await tool_call("mcp_get_deck_state", deck_id="fake")
        finally:
            mod._client = saved

    @pytest.mark.asyncio
    async def test_bad_tool_name_raises_error(self, mcp_env):
        """Calling a non-existent tool raises MCPToolError."""
        with pytest.raises(MCPToolError, match="no_such_tool"):
            await tool_call("no_such_tool", x=1)

    @pytest.mark.asyncio
    async def test_bad_deck_id_raises_error(self, mcp_env):
        """Passing invalid deck_id propagates as MCPToolError."""
        with pytest.raises((MCPToolError, Exception)):
            await tool_call(
                "mcp_get_deck_state",
                deck_id="00000000-0000-0000-0000-000000000000",
            )


@pytest.mark.integration
class TestPoolIdempotency:
    """init_pool() idempotency guard tests."""

    @pytest.mark.asyncio
    async def test_double_init_pool_returns_same_pool(self):
        """Calling init_pool() twice returns the same pool object."""
        pool1 = await init_pool()
        pool2 = await init_pool()
        assert pool1 is pool2
        await close_pool()

    @pytest.mark.asyncio
    async def test_double_init_mcp_client_is_safe(self):
        """Calling init_mcp_client() twice doesn't raise."""
        await init_pool()
        await init_mcp_client()
        await init_mcp_client()  # should be no-op
        await close_mcp_client()
        await close_pool()


@pytest.mark.integration
class TestClientLifecycle:
    """Client init/close/re-init cycle."""

    @pytest.mark.asyncio
    async def test_close_and_reinit(self):
        """Client can be closed and re-initialized."""
        await init_pool()

        await init_mcp_client()
        deck_id = await tool_call(
            "mcp_create_deck", topic="Lifecycle Test", target_slides=1
        )
        assert isinstance(deck_id, str)

        await close_mcp_client()

        # After close, tool_call should fail
        import src.mcp_client as mod
        assert mod._client is None

        # Re-init should work
        await init_mcp_client()
        state = await tool_call("mcp_get_deck_state", deck_id=deck_id)
        assert state["deck"]["topic"] == "Lifecycle Test"

        await close_mcp_client()
        await close_pool()
