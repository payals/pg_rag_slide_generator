"""
Integration tests for the Generation Loop (Phase 4).

Tests end-to-end generation with mocked LLM and DB calls.
Verifies gate sequence, retry logic, and state transitions.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.orchestrator import (
    create_initial_state,
    build_orchestrator_graph,
    GraphState,
)
from src.llm import LLMResponse
from tests.helpers.mock_tool_call import make_tool_mock, seq


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def test_deck_id():
    """Generate a test deck ID."""
    return str(uuid4())


def _mock_llm_response() -> LLMResponse:
    return LLMResponse(text="", prompt_tokens=100, completion_tokens=50)


@pytest.fixture
def mock_slide_response():
    """Factory for mock slide responses (returns (dict, LLMResponse) tuple)."""
    def _create(intent: str, title: str):
        slide = {
            "title": title,
            "intent": intent,
            "bullets": [
                f"First point about {intent}",
                f"Second point about {intent}",
                f"Third point about {intent}",
            ],
            "speaker_notes": f"This slide covers {intent}...",
            "citations": [
                {
                    "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
                    "doc_title": "Test Document",
                    "relevance": "Relevant to topic",
                }
            ],
        }
        return slide, _mock_llm_response()
    return _create


@pytest.fixture
def mock_chunks():
    """Mock search results."""
    return [
        {"chunk_id": "c1", "content": "Test", "combined_score": 0.9, "doc_title": "Doc", "trust_level": "high"},
        {"chunk_id": "c2", "content": "Test 2", "combined_score": 0.8, "doc_title": "Doc", "trust_level": "high"},
        {"chunk_id": "c3", "content": "Test 3", "combined_score": 0.7, "doc_title": "Doc", "trust_level": "medium"},
    ]


def _build_tool_responses(mock_chunks, mock_slide_response, pick_sequence, commit_result=None):
    """Build a standard responses dict for the full generation pipeline."""
    return {
        "mcp_pick_next_intent": seq(*pick_sequence),
        "mcp_search_chunks": mock_chunks,
        "mcp_get_deck_state": {"coverage": {"covered": []}},
        "mcp_validate_slide_structure": {"is_valid": True, "errors": []},
        "mcp_validate_citations": {"is_valid": True, "citation_count": 1, "errors": []},
        "mcp_check_grounding": {"is_grounded": True, "min_similarity": 0.8, "ungrounded_bullets": []},
        "mcp_check_novelty": {"is_novel": True, "max_similarity": 0.3, "most_similar_slide_no": None},
        "mcp_commit_slide": commit_result or {"success": True, "slide_id": str(uuid4()), "errors": []},
    }


# =============================================================================
# STATE MACHINE TESTS
# =============================================================================

class TestGraphCompilation:
    """Tests for LangGraph state machine compilation."""
    
    def test_graph_compiles(self):
        """Graph should compile without errors."""
        graph = build_orchestrator_graph()
        compiled = graph.compile()
        
        assert compiled is not None
    
    def test_graph_has_correct_entry_point(self):
        """Graph should start at pick_intent."""
        graph = build_orchestrator_graph()
        
        assert "pick_intent" in graph.nodes


class TestGenerationWithMockedLLM:
    """Tests for generation loop with mocked LLM calls."""
    
    @pytest.mark.asyncio
    async def test_generates_single_slide(self, test_deck_id, mock_slide_response, mock_chunks):
        """Should generate a single slide with mocked LLM."""
        responses = _build_tool_responses(mock_chunks, mock_slide_response, ["problem", None])

        with patch("src.orchestrator.tool_call", side_effect=make_tool_mock(responses)), \
             patch("src.orchestrator.draft_slide", new_callable=AsyncMock) as mock_draft:
            
            mock_draft.return_value = mock_slide_response("problem", "The AI Infrastructure Problem")
            
            state = create_initial_state(test_deck_id)
            state["target_slides"] = 1
            
            graph = build_orchestrator_graph()
            compiled = graph.compile()
            
            final_state = await compiled.ainvoke(state)
            
            assert final_state["is_complete"] is True
            assert len(final_state["generated_slides"]) == 1
            assert "problem" in final_state["generated_slides"]
    
    @pytest.mark.asyncio
    async def test_retries_on_format_failure(self, test_deck_id, mock_slide_response, mock_chunks):
        """Should retry when format validation fails."""
        responses = {
            "mcp_pick_next_intent": seq("problem", None),
            "mcp_search_chunks": mock_chunks,
            "mcp_get_deck_state": {"coverage": {"covered": []}},
            "mcp_validate_slide_structure": seq(
                {"is_valid": False, "errors": ["Bullet too long"]},
                {"is_valid": True, "errors": []},
                {"is_valid": True, "errors": []},
                {"is_valid": True, "errors": []},
            ),
            "mcp_validate_citations": {"is_valid": True, "citation_count": 1, "errors": []},
            "mcp_check_grounding": {"is_grounded": True, "min_similarity": 0.8, "ungrounded_bullets": []},
            "mcp_check_novelty": {"is_novel": True, "max_similarity": 0.3},
            "mcp_commit_slide": {"success": True, "slide_id": str(uuid4()), "errors": []},
        }

        with patch("src.orchestrator.tool_call", side_effect=make_tool_mock(responses)), \
             patch("src.orchestrator.draft_slide", new_callable=AsyncMock) as mock_draft, \
             patch("src.orchestrator.rewrite_slide_format", new_callable=AsyncMock) as mock_rewrite:
            
            mock_draft.return_value = (
                {
                    "title": "Bad Slide",
                    "intent": "problem",
                    "bullets": ["Too long " * 50],
                },
                _mock_llm_response(),
            )
            mock_rewrite.return_value = mock_slide_response("problem", "The AI Infrastructure Problem")
            
            state = create_initial_state(test_deck_id)
            state["target_slides"] = 1
            
            graph = build_orchestrator_graph()
            compiled = graph.compile()
            
            final_state = await compiled.ainvoke(state)
            
            assert final_state["total_retries"] >= 1
            assert len(final_state["generated_slides"]) == 1


# =============================================================================
# GATE SEQUENCE TESTS
# =============================================================================

class TestGateSequence:
    """Tests for gate validation sequence."""
    
    @pytest.mark.asyncio
    async def test_gates_called_in_order(self, test_deck_id, mock_slide_response, mock_chunks):
        """Gates should be called in correct order: G1 -> G3 -> G2 -> G2.5 -> G4 -> G5."""
        call_order = []

        async def _tracking_dispatch(name, **kwargs):
            if name == "mcp_pick_next_intent":
                return ["problem", None].pop(0) if not hasattr(_tracking_dispatch, '_pick_idx') else None
            if name == "mcp_search_chunks":
                call_order.append("G1")
                return mock_chunks
            if name == "mcp_get_deck_state":
                return {"coverage": {"covered": []}}
            if name == "mcp_validate_slide_structure":
                call_order.append("G3")
                return {"is_valid": True, "errors": []}
            if name == "mcp_validate_citations":
                call_order.append("G2")
                return {"is_valid": True, "citation_count": 1, "errors": []}
            if name == "mcp_check_grounding":
                call_order.append("G2.5")
                return {"is_grounded": True, "min_similarity": 0.8, "ungrounded_bullets": []}
            if name == "mcp_check_novelty":
                call_order.append("G4")
                return {"is_novel": True, "max_similarity": 0.3, "most_similar_slide_no": None}
            if name == "mcp_commit_slide":
                call_order.append("G5")
                return {"success": True, "slide_id": str(uuid4()), "errors": []}
            raise ValueError(f"Unmocked: {name}")

        pick_calls = iter(["problem", None])
        async def _dispatch(name, **kwargs):
            if name == "mcp_pick_next_intent":
                return next(pick_calls)
            return await _tracking_dispatch(name, **kwargs)

        with patch("src.orchestrator.tool_call", side_effect=_dispatch), \
             patch("src.orchestrator.draft_slide", new_callable=AsyncMock) as mock_draft:
            
            mock_draft.return_value = mock_slide_response("problem", "Test")
            
            state = create_initial_state(test_deck_id)
            state["target_slides"] = 1
            
            graph = build_orchestrator_graph()
            compiled = graph.compile()
            
            await compiled.ainvoke(state)
            
            expected_order = ["G1", "G3", "G2", "G2.5", "G4", "G5"]
            assert call_order == expected_order, f"Expected {expected_order}, got {call_order}"


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestErrorHandling:
    """Tests for error handling and graceful degradation."""
    
    @pytest.mark.asyncio
    async def test_handles_insufficient_context(self, test_deck_id, mock_slide_response, mock_chunks):
        """Should handle InsufficientContextError and retry with new query."""
        from src.llm import InsufficientContextError
        
        draft_calls = 0
        
        async def mock_draft_with_insufficient(*args, **kwargs):
            nonlocal draft_calls
            draft_calls += 1
            if draft_calls == 1:
                raise InsufficientContextError("Missing benchmark data")
            return mock_slide_response("problem", "Test")

        responses = _build_tool_responses(mock_chunks, mock_slide_response, ["problem", None])

        with patch("src.orchestrator.tool_call", side_effect=make_tool_mock(responses)), \
             patch("src.orchestrator.draft_slide", side_effect=mock_draft_with_insufficient), \
             patch("src.orchestrator.generate_alternative_queries", new_callable=AsyncMock) as mock_alt_queries:
            
            mock_alt_queries.return_value = (
                ["alternative query 1", "alternative query 2"],
                _mock_llm_response(),
            )
            
            state = create_initial_state(test_deck_id)
            state["target_slides"] = 1
            
            graph = build_orchestrator_graph()
            compiled = graph.compile()
            
            final_state = await compiled.ainvoke(state)
            
            mock_alt_queries.assert_called_once()
            assert len(final_state["generated_slides"]) == 1
    
    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self, test_deck_id, mock_chunks):
        """Should give up on slide after max retries."""
        from src.llm import ParseError
        
        responses = {
            "mcp_pick_next_intent": seq("problem", None),
            "mcp_search_chunks": mock_chunks,
            "mcp_get_deck_state": {"coverage": {"covered": []}},
        }

        with patch("src.orchestrator.tool_call", side_effect=make_tool_mock(responses)), \
             patch("src.orchestrator.draft_slide", new_callable=AsyncMock) as mock_draft:
            
            mock_draft.side_effect = ParseError("bad json", "JSON decode error")
            
            state = create_initial_state(test_deck_id)
            state["target_slides"] = 1
            state["max_retries_per_slide"] = 3
            
            graph = build_orchestrator_graph()
            compiled = graph.compile()
            
            final_state = await compiled.ainvoke(state)
            
            assert len(final_state["generated_slides"]) == 0
            assert final_state["total_retries"] >= 3


# =============================================================================
# METRICS TESTS
# =============================================================================

class TestMetricsTracking:
    """Tests for metrics tracking."""
    
    @pytest.mark.asyncio
    async def test_tracks_llm_calls(self, test_deck_id, mock_slide_response, mock_chunks):
        """Should track number of LLM calls."""
        responses = _build_tool_responses(mock_chunks, mock_slide_response, ["problem", None])

        with patch("src.orchestrator.tool_call", side_effect=make_tool_mock(responses)), \
             patch("src.orchestrator.draft_slide", new_callable=AsyncMock) as mock_draft:
            
            mock_draft.return_value = mock_slide_response("problem", "Test")
            
            state = create_initial_state(test_deck_id)
            state["target_slides"] = 1
            
            graph = build_orchestrator_graph()
            compiled = graph.compile()
            
            final_state = await compiled.ainvoke(state)
            
            assert final_state["llm_calls"] >= 1
    
    @pytest.mark.asyncio
    async def test_tracks_embeddings(self, test_deck_id, mock_slide_response, mock_chunks):
        """Should track embeddings generated."""
        responses = _build_tool_responses(mock_chunks, mock_slide_response, ["problem", None])

        with patch("src.orchestrator.tool_call", side_effect=make_tool_mock(responses)), \
             patch("src.orchestrator.draft_slide", new_callable=AsyncMock) as mock_draft:
            
            mock_draft.return_value = mock_slide_response("problem", "Test")
            
            state = create_initial_state(test_deck_id)
            state["target_slides"] = 1
            
            graph = build_orchestrator_graph()
            compiled = graph.compile()
            
            final_state = await compiled.ainvoke(state)
            
            # 3 bullets + 1 novelty check = 4
            assert final_state["embeddings_generated"] >= 4
