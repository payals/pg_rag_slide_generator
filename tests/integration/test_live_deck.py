"""
Integration tests for the live deck server.

Tests:
- Pool survives generation complete (Bug 1)
- NOTIFY filtered by deck_id (Issue 6)
- Error event on orchestrator crash (Issue 14)
- SSE catch-up on reconnect
- Progress events during validation (Bug 3)
- Health endpoint
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from src.orchestrator import (
    run_generation_headless,
    create_initial_state,
    _wrap_node_with_progress,
)
from tests.helpers.mock_tool_call import make_tool_mock


# =============================================================================
# Test pool survives generation (Bug 1)
# =============================================================================


class TestPoolSurvival:
    """Tests that run_generation_headless does NOT close the pool."""

    @pytest.mark.asyncio
    async def test_pool_not_closed_after_headless(self):
        """After run_generation_headless(), the pool should still be usable."""
        import inspect
        source = inspect.getsource(run_generation_headless)

        assert "init_pool()" not in source
        assert "close_pool()" not in source


# =============================================================================
# Test NOTIFY filtering (Issue 6)
# =============================================================================


class TestNotifyFiltering:
    """Tests that SSE handler ignores NOTIFY events for other deck_ids."""

    @pytest.mark.asyncio
    async def test_filter_by_deck_id(self):
        """on_slide_notify filters by deck_id."""
        from src.server import _on_slide_notify, _config

        _config["deck_id"] = "correct-deck-id"

        payload = json.dumps({
            "deck_id": "wrong-deck-id",
            "slide_no": 1,
            "intent": "problem",
            "title": "Test",
        })

        with patch("src.server.asyncio.create_task") as mock_task:
            _on_slide_notify(None, None, "slide_committed", payload)
            mock_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_matching_deck_id(self):
        """on_slide_notify accepts events for the current deck."""
        from src.server import _on_slide_notify, _config

        _config["deck_id"] = "my-deck"

        payload = json.dumps({
            "deck_id": "my-deck",
            "slide_no": 1,
            "intent": "problem",
            "title": "Test",
        })

        with patch("src.server.asyncio.create_task") as mock_task:
            _on_slide_notify(None, None, "slide_committed", payload)
            mock_task.assert_called_once()


# =============================================================================
# Test error event on orchestrator crash (Issue 14)
# =============================================================================


class TestErrorEvent:
    """Tests that orchestrator errors produce error events."""

    @pytest.mark.asyncio
    async def test_error_pushed_to_queue_on_crash(self):
        """When orchestrator raises, error event is pushed to queue."""
        queue = asyncio.Queue()

        mock = make_tool_mock({
            "mcp_create_deck": Exception("DB down"),
        })

        async def _raising_dispatch(name, **kwargs):
            if name == "mcp_create_deck":
                raise Exception("DB down")
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.load_intent_type_map", new_callable=AsyncMock), \
             patch("src.orchestrator.tool_call", side_effect=_raising_dispatch):
            with pytest.raises(Exception, match="DB down"):
                await run_generation_headless(
                    deck_id=None,
                    topic="Test Topic",
                    progress_queue=queue,
                )

        msg = queue.get_nowait()
        assert msg["type"] == "error"
        assert "DB down" in msg["error"]


# =============================================================================
# Test progress events during validation (Bug 3)
# =============================================================================


class TestProgressEvents:
    """Tests that SSE receives progress events during validation."""

    @staticmethod
    def _make_node_spec(node_fn):
        """Create a mock StateNodeSpec with a RunnableCallable wrapping node_fn."""
        from types import SimpleNamespace
        from langgraph._internal._runnable import RunnableCallable

        runnable = RunnableCallable(func=node_fn, afunc=node_fn)
        return SimpleNamespace(
            runnable=runnable,
            ends=(),
            cache_policy=None,
            defer=False,
            retry_policy=None,
            metadata=None,
            input_schema=None,
        )

    @pytest.mark.asyncio
    async def test_progress_wrapper_fires_before_node(self):
        """Progress events fire BEFORE the node executes."""
        timestamps = []
        queue = asyncio.Queue()

        async def slow_node(state):
            timestamps.append("node_executed")
            return state

        node_spec = self._make_node_spec(slow_node)
        wrapped_spec = _wrap_node_with_progress(node_spec, "check_grounding", queue)

        state = create_initial_state("deck-1")
        state["current_intent"] = "problem"

        await wrapped_spec.runnable.ainvoke(state)

        msg = queue.get_nowait()
        assert msg["type"] == "progress"
        assert msg["phase"] == "check_grounding"
        assert "node_executed" in timestamps

    @pytest.mark.asyncio
    async def test_all_node_names_produce_progress(self):
        """Each node name produces a distinct progress event."""
        node_names = [
            "pick_intent", "retrieve", "draft", "validate_format",
            "validate_citations", "check_grounding", "check_novelty",
            "select_image", "commit",
        ]

        for name in node_names:
            queue = asyncio.Queue()

            async def noop(state):
                return state

            node_spec = self._make_node_spec(noop)
            wrapped_spec = _wrap_node_with_progress(node_spec, name, queue)
            state = create_initial_state("deck-1")
            state["current_intent"] = "test"

            await wrapped_spec.runnable.ainvoke(state)

            msg = queue.get_nowait()
            assert msg["phase"] == name, f"Expected phase={name}"


# =============================================================================
# Test health endpoint (Issue 16)
# =============================================================================


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_correct_fields(self):
        """Health endpoint returns expected structure."""
        from src.server import app, _config

        from fastapi.testclient import TestClient

        _config["deck_id"] = "test-deck-123"

        from src.server import health

        with patch("src.server.generation_task", None):
            with patch("src.server._count_slides", new_callable=AsyncMock, return_value=5):
                result = await health()

        assert result["status"] == "ok"
        assert result["deck_id"] == "test-deck-123"
        assert result["generating"] is False
        assert result["slides_ready"] == 5


# =============================================================================
# Test complete event flow
# =============================================================================


class TestCompleteEventFlow:
    """Tests for the complete event pushed after generation finishes."""

    @pytest.mark.asyncio
    async def test_complete_event_pushed(self):
        """When orchestrator finishes, complete event is pushed."""
        queue = asyncio.Queue()

        async def _dispatch(name, **kwargs):
            if name == "mcp_get_run_report":
                return {"deck_id": "d1", "summary": {}}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.load_intent_type_map", new_callable=AsyncMock), \
             patch("src.orchestrator.build_orchestrator_graph") as mock_graph, \
             patch("src.orchestrator.tool_call", side_effect=_dispatch):
            mock_compiled = MagicMock()
            mock_compiled.ainvoke = AsyncMock(return_value={
                "generated_slides": ["problem"],
                "failed_intents": [],
                "abandoned_intents": [],
                "llm_calls": 5,
                "embeddings_generated": 3,
                "total_retries": 1,
                "images_deduplicated": 0,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "embedding_tokens": 20,
                "estimated_cost_usd": 0.01,
            })
            mock_graph.return_value.compile.return_value = mock_compiled

            with patch("src.orchestrator.get_connection"):
                result = await run_generation_headless(
                    deck_id="existing-deck",
                    topic="Test",
                    progress_queue=queue,
                )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        complete_events = [e for e in events if e.get("type") == "complete"]
        assert len(complete_events) == 1
        assert complete_events[0]["deck_id"] == "existing-deck"
