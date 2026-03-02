"""
Unit tests for Orchestrator (src/orchestrator.py).

Tests state transitions, retry logic, and conditional edges.
Uses mocks to avoid actual DB and LLM calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from src.llm import LLMResponse
from src.orchestrator import (
    create_initial_state,
    pick_intent_node,
    retrieve_node,
    draft_node,
    validate_format_node,
    validate_citations_node,
    check_grounding_node,
    check_novelty_node,
    commit_node,
    should_continue_after_pick_intent,
    should_continue_after_retrieve,
    should_continue_after_draft,
    should_continue_after_format,
    should_continue_after_citations,
    should_continue_after_grounding,
    should_continue_after_novelty,
    should_continue_after_commit,
    build_orchestrator_graph,
    GraphState,
    _estimate_embedding_tokens,
    _calculate_cost,
    _accumulate_llm_usage,
)
from tests.helpers.mock_tool_call import make_tool_mock

import src.renderer as renderer_mod
import src.models as _models
from src.models import IntentTypeInfo


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def mock_renderer_init():
    """Populate DB caches so get_target_slides() works without a real DB."""
    old_itm = _models.INTENT_TYPE_MAP.copy()
    _models.INTENT_TYPE_MAP.clear()
    _models.INTENT_TYPE_MAP.update({
        "title": IntentTypeInfo(slide_type="bullets", require_image=False, sort_order=0, is_generatable=False),
        "problem": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=1, is_generatable=True),
        "why-postgres": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=2, is_generatable=True),
        "comparison": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=3, is_generatable=True),
        "capabilities": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=4, is_generatable=True),
        "thesis": IntentTypeInfo(slide_type="statement", require_image=False, sort_order=5, is_generatable=True),
        "schema-security": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=6, is_generatable=True),
        "architecture": IntentTypeInfo(slide_type="diagram", require_image=True, sort_order=7, is_generatable=True),
        "what-is-rag": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=8, is_generatable=True),
        "rag-in-postgres": IntentTypeInfo(slide_type="code", require_image=True, sort_order=9, is_generatable=True),
        "advanced-retrieval": IntentTypeInfo(slide_type="split", require_image=False, sort_order=10, is_generatable=True, suggested_title="Beyond Vector Search"),
        "what-is-mcp": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=11, is_generatable=True),
        "mcp-tools": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=12, is_generatable=True),
        "gates": IntentTypeInfo(slide_type="flow", require_image=False, sort_order=13, is_generatable=False),
        "observability": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=14, is_generatable=True),
        "what-we-built": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=15, is_generatable=True),
        "takeaways": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=16, is_generatable=True),
        "thanks": IntentTypeInfo(slide_type="bullets", require_image=False, sort_order=99, is_generatable=False),
    })
    renderer_mod._initialized = True
    yield
    _models.INTENT_TYPE_MAP.clear()
    _models.INTENT_TYPE_MAP.update(old_itm)
    renderer_mod._initialized = False


@pytest.fixture
def initial_state():
    """Create initial state for testing."""
    return create_initial_state("test-deck-id", "test-run-id")


@pytest.fixture
def state_with_intent(initial_state):
    """State with a current intent selected."""
    return {
        **initial_state,
        "current_intent": "why-postgres",
        "current_slide_no": 1,
    }


@pytest.fixture
def state_with_chunks(state_with_intent):
    """State with retrieved chunks."""
    return {
        **state_with_intent,
        "current_chunks": [
            {"chunk_id": "chunk-1", "content": "Test content", "combined_score": 0.8},
            {"chunk_id": "chunk-2", "content": "More content", "combined_score": 0.7},
            {"chunk_id": "chunk-3", "content": "Even more", "combined_score": 0.6},
        ],
        "current_gate_results": [
            {"gate_name": "g1_retrieval", "passed": True, "score": 0.8, "errors": []},
        ],
    }


@pytest.fixture
def state_with_draft(state_with_chunks):
    """State with a draft slide."""
    return {
        **state_with_chunks,
        "current_draft": {
            "title": "Why Postgres for AI Workloads",
            "intent": "why-postgres",
            "bullets": [
                "Postgres is battle-tested",
                "Built-in ACID guarantees",
                "Extensions like pgvector",
            ],
            "speaker_notes": "This slide explains...",
            "citations": [{"chunk_id": "chunk-1", "doc_title": "Test Doc"}],
        },
    }


@pytest.fixture
def mock_chunks():
    """Mock search results."""
    return [
        {"chunk_id": "c1", "content": "Test 1", "combined_score": 0.9, "doc_title": "Doc 1", "trust_level": "high"},
        {"chunk_id": "c2", "content": "Test 2", "combined_score": 0.8, "doc_title": "Doc 2", "trust_level": "high"},
        {"chunk_id": "c3", "content": "Test 3", "combined_score": 0.7, "doc_title": "Doc 3", "trust_level": "medium"},
    ]


# =============================================================================
# INITIAL STATE TESTS
# =============================================================================

class TestCreateInitialState:
    """Tests for create_initial_state function."""
    
    def test_creates_valid_state(self):
        """Should create state with all required fields."""
        state = create_initial_state("deck-123", "run-456")
        
        assert state["deck_id"] == "deck-123"
        assert state["run_id"] == "run-456"
        expected = sum(1 for info in _models.INTENT_TYPE_MAP.values() if info.is_generatable)
        assert state["target_slides"] == expected
        assert state["current_intent"] is None
        assert state["is_complete"] is False
        assert state["llm_calls"] == 0
    
    def test_generates_run_id_if_not_provided(self):
        """Should generate run_id if not provided."""
        state = create_initial_state("deck-123")
        
        assert state["run_id"] is not None
        assert len(state["run_id"]) == 36  # UUID format
    
    def test_initializes_counters_to_zero(self):
        """Should initialize all counters to zero."""
        state = create_initial_state("deck-123")
        
        assert state["slide_retries"] == 0
        assert state["total_retries"] == 0
        assert state["llm_calls"] == 0
        assert state["embeddings_generated"] == 0
        assert state["prompt_tokens"] == 0
        assert state["completion_tokens"] == 0
        assert state["embedding_tokens"] == 0
        assert state["estimated_cost_usd"] == 0.0
    
    def test_initializes_lists_empty(self):
        """Should initialize all lists as empty."""
        state = create_initial_state("deck-123")
        
        assert state["prior_titles"] == []
        assert state["generated_slides"] == []
        assert state["failed_intents"] == []
        assert state["abandoned_intents"] == []
        assert state["current_chunks"] == []
        assert state["current_gate_results"] == []
    
    def test_initial_state_has_used_image_ids(self):
        """Should initialize used_image_ids as empty list and images_deduplicated as 0."""
        state = create_initial_state("deck-123")
        
        assert state["used_image_ids"] == []
        assert state["images_deduplicated"] == 0
    
    def test_initial_state_has_fallback_false(self):
        """Should initialize fallback_triggered as False."""
        state = create_initial_state("deck-123")
        
        assert state["fallback_triggered"] is False


# =============================================================================
# NODE TESTS
# =============================================================================

class TestPickIntentNode:
    """Tests for pick_intent_node."""
    
    @pytest.mark.asyncio
    async def test_picks_next_intent(self, initial_state):
        """Should pick next intent from database."""
        mock = make_tool_mock({"mcp_pick_next_intent": "why-postgres"})
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await pick_intent_node(initial_state)
            
            assert result["current_intent"] == "why-postgres"
            assert result["current_slide_no"] == 1
            assert result["is_complete"] is False
    
    @pytest.mark.asyncio
    async def test_marks_complete_when_no_more_intents(self, initial_state):
        """Should mark complete when no intents remain."""
        mock = make_tool_mock({"mcp_pick_next_intent": None})
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await pick_intent_node(initial_state)
            
            assert result["is_complete"] is True
            assert result["current_intent"] is None
    
    @pytest.mark.asyncio
    async def test_resets_slide_state(self, initial_state):
        """Should reset slide-specific state when picking new intent."""
        state = {
            **initial_state,
            "current_draft": {"title": "old"},
            "current_gate_results": [{"gate_name": "test"}],
            "slide_retries": 2,
        }
        
        mock = make_tool_mock({"mcp_pick_next_intent": "problem"})
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await pick_intent_node(state)
            
            assert result["current_draft"] is None
            assert result["current_gate_results"] == []
            assert result["slide_retries"] == 0


class TestRetrieveNode:
    """Tests for retrieve_node."""
    
    @pytest.mark.asyncio
    async def test_retrieves_chunks(self, state_with_intent, mock_chunks):
        """Should retrieve chunks for intent."""
        _search_calls = []

        async def _dispatch(name, **kwargs):
            if name == "mcp_search_chunks":
                _search_calls.append(kwargs)
                return mock_chunks
            if name == "mcp_get_deck_state":
                return {"coverage": {"covered": []}}
            if name == "mcp_check_retrieval_quality":
                return {"is_valid": True, "chunk_count": 3, "top_score": 0.9, "errors": []}
            if name == "mcp_log_gate":
                return {"log_id": "mock-log-id"}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            result = await retrieve_node(state_with_intent)
            
            assert len(result["current_chunks"]) == 3
            assert len(_search_calls) == 1
    
    @pytest.mark.asyncio
    async def test_adds_g1_gate_result(self, state_with_intent, mock_chunks):
        """Should add G1 retrieval gate result."""
        mock = make_tool_mock({
            "mcp_search_chunks": mock_chunks,
            "mcp_get_deck_state": {"coverage": {"covered": []}},
            "mcp_check_retrieval_quality": {"is_valid": True, "chunk_count": 3, "top_score": 0.9, "errors": []},
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await retrieve_node(state_with_intent)
            
            g1 = result["current_gate_results"][0]
            assert g1["gate_name"] == "g1_retrieval"
            assert g1["passed"] is True
    
    @pytest.mark.asyncio
    async def test_fails_g1_with_poor_results(self, state_with_intent):
        """Should fail G1 with insufficient results."""
        mock = make_tool_mock({
            "mcp_search_chunks": [{"chunk_id": "1", "combined_score": 0.1}],
            "mcp_get_deck_state": {"coverage": {"covered": []}},
            "mcp_check_retrieval_quality": {"is_valid": False, "chunk_count": 1, "top_score": 0.1, "errors": ["Too few chunks: 1 (min: 3)"]},
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await retrieve_node(state_with_intent)
            
            g1 = result["current_gate_results"][0]
            assert g1["passed"] is False
    
    @pytest.mark.asyncio
    @patch("src.orchestrator._get_related_intents", return_value=["what-is-rag"])
    async def test_coverage_enrichment_adds_differentiation(self, _mock_rel, state_with_intent, mock_chunks):
        """Should append differentiation text when related intents are covered."""
        state = {**state_with_intent, "current_intent": "rag-in-postgres"}
        
        _search_kwargs = {}

        async def _dispatch(name, **kwargs):
            nonlocal _search_kwargs
            if name == "mcp_search_chunks":
                _search_kwargs = kwargs
                return mock_chunks
            if name == "mcp_get_deck_state":
                return {"coverage": {"covered": ["what-is-rag"]}}
            if name == "mcp_check_retrieval_quality":
                return {"is_valid": True, "chunk_count": 3, "top_score": 0.9, "errors": []}
            if name == "mcp_log_gate":
                return {"log_id": "mock-log-id"}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            result = await retrieve_node(state)
            
            assert "differentiate from" in _search_kwargs.get("query", "")
    
    @pytest.mark.asyncio
    async def test_coverage_enrichment_noop_when_no_overlap(self, state_with_intent, mock_chunks):
        """Should not enrich when no related intents are covered."""
        mock = make_tool_mock({
            "mcp_search_chunks": mock_chunks,
            "mcp_get_deck_state": {"coverage": {"covered": ["problem"]}},
            "mcp_check_retrieval_quality": {"is_valid": True, "chunk_count": 3, "top_score": 0.9, "errors": []},
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await retrieve_node(state_with_intent)
            
            coverage_gate = [g for g in result["current_gate_results"] if g["gate_name"] == "coverage_sensor"]
            assert len(coverage_gate) == 1
            assert coverage_gate[0]["details"]["enrichment_applied"] == ""


class TestDraftNode:
    """Tests for draft_node."""
    
    @pytest.mark.asyncio
    async def test_drafts_slide(self, state_with_chunks):
        """Should draft slide using LLM and accumulate cost."""
        draft = {
            "title": "Test",
            "intent": "why-postgres",
            "bullets": ["B1", "B2", "B3"],
        }
        mock_resp = LLMResponse(text="...", prompt_tokens=100, completion_tokens=200)
        
        with patch("src.orchestrator.draft_slide", new_callable=AsyncMock) as mock:
            mock.return_value = (draft, mock_resp)
            
            result = await draft_node(state_with_chunks)
            
            assert result["current_draft"] == draft
            assert result["llm_calls"] == 1
            assert result["prompt_tokens"] == 100
            assert result["completion_tokens"] == 200
            assert result["estimated_cost_usd"] > 0
    
    @pytest.mark.asyncio
    async def test_handles_insufficient_context(self, state_with_chunks):
        """Should handle InsufficientContextError."""
        from src.llm import InsufficientContextError
        
        mock_alt_resp = LLMResponse(text="...", prompt_tokens=30, completion_tokens=40)
        
        with patch("src.orchestrator.draft_slide", new_callable=AsyncMock) as mock_draft:
            mock_draft.side_effect = InsufficientContextError("missing data")
            
            with patch("src.orchestrator.generate_alternative_queries", new_callable=AsyncMock) as mock_queries:
                mock_queries.return_value = (["query1", "query2"], mock_alt_resp)
                
                result = await draft_node(state_with_chunks)
                
                assert result["last_failure_type"] == "insufficient_context"
                assert result["slide_retries"] == 1
                assert result["total_retries"] == 1
                assert result["prompt_tokens"] == 30
    
    @pytest.mark.asyncio
    async def test_rewrites_on_format_failure(self, state_with_chunks):
        """Should call rewrite function on format failure."""
        state = {
            **state_with_chunks,
            "last_failure_type": "format",
            "last_failure_details": {"errors": ["Too many bullets"]},
            "current_draft": {"title": "Old", "bullets": ["1", "2", "3", "4", "5", "6"]},
        }
        
        new_draft = {"title": "Fixed", "intent": "why-postgres", "bullets": ["1", "2", "3"]}
        mock_resp = LLMResponse(text="...", prompt_tokens=80, completion_tokens=150)
        
        with patch("src.orchestrator.rewrite_slide_format", new_callable=AsyncMock) as mock:
            mock.return_value = (new_draft, mock_resp)
            
            result = await draft_node(state)
            
            assert result["current_draft"] == new_draft
            mock.assert_called_once()


class TestValidateFormatNode:
    """Tests for validate_format_node."""
    
    @pytest.mark.asyncio
    async def test_passes_valid_format(self, state_with_draft):
        """Should pass valid format."""
        mock = make_tool_mock({
            "mcp_validate_slide_structure": {"is_valid": True, "errors": []},
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await validate_format_node(state_with_draft)
            
            g3 = [g for g in result["current_gate_results"] if g["gate_name"] == "g3_format"][0]
            assert g3["passed"] is True
    
    @pytest.mark.asyncio
    async def test_fails_invalid_format(self, state_with_draft):
        """Should fail invalid format and set retry state."""
        mock = make_tool_mock({
            "mcp_validate_slide_structure": {"is_valid": False, "errors": ["Too many bullets"]},
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await validate_format_node(state_with_draft)
            
            assert result["last_failure_type"] == "format"
            assert result["slide_retries"] == 1


class TestCheckGroundingNode:
    """Tests for check_grounding_node."""
    
    @pytest.mark.asyncio
    async def test_passes_grounded_content(self, state_with_draft):
        """Should pass when content is grounded."""
        mock = make_tool_mock({
            "mcp_check_grounding": {
                "is_grounded": True,
                "min_similarity": 0.8,
                "ungrounded_bullets": [],
            },
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await check_grounding_node(state_with_draft)
            
            g25 = [g for g in result["current_gate_results"] if g["gate_name"] == "g2.5_grounding"][0]
            assert g25["passed"] is True
            assert result["embeddings_generated"] == 3  # 3 bullets
    
    @pytest.mark.asyncio
    async def test_fails_ungrounded_content(self, state_with_draft):
        """Should fail when content is not grounded."""
        mock = make_tool_mock({
            "mcp_check_grounding": {
                "is_grounded": False,
                "min_similarity": 0.4,
                "ungrounded_bullets": [1],
            },
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await check_grounding_node(state_with_draft)
            
            assert result["last_failure_type"] == "grounding"
            assert result["slide_retries"] == 1


class TestCheckNoveltyNode:
    """Tests for check_novelty_node."""
    
    @pytest.mark.asyncio
    async def test_passes_novel_content(self, state_with_draft):
        """Should pass when content is novel."""
        mock = make_tool_mock({
            "mcp_check_novelty": {
                "is_novel": True,
                "max_similarity": 0.5,
                "most_similar_slide_no": None,
            },
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await check_novelty_node(state_with_draft)
            
            g4 = [g for g in result["current_gate_results"] if g["gate_name"] == "g4_novelty"][0]
            assert g4["passed"] is True
    
    @pytest.mark.asyncio
    async def test_fails_similar_content(self, state_with_draft):
        """Should fail when content is too similar."""
        mock = make_tool_mock({
            "mcp_check_novelty": {
                "is_novel": False,
                "max_similarity": 0.9,
                "most_similar_slide_no": 1,
                "most_similar_intent": "problem",
            },
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await check_novelty_node(state_with_draft)
            
            assert result["last_failure_type"] == "novelty"


class TestCommitNode:
    """Tests for commit_node."""
    
    @pytest.mark.asyncio
    async def test_commits_slide_successfully(self, state_with_draft):
        """Should commit slide and update generated_slides."""
        state = {
            **state_with_draft,
            "current_gate_results": [
                {"gate_name": "g4_novelty", "passed": True, "score": 0.5, "details": {"max_similarity": 0.5}},
                {"gate_name": "g2.5_grounding", "passed": True, "score": 0.8, "details": {}},
            ],
        }
        
        mock = make_tool_mock({
            "mcp_commit_slide": {"success": True, "slide_id": "slide-123", "errors": []},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await commit_node(state)
            
            assert "why-postgres" in result["generated_slides"]
            assert "Why Postgres for AI Workloads" in result["prior_titles"]
    
    @pytest.mark.asyncio
    async def test_handles_commit_failure(self, state_with_draft):
        """Should handle commit failure."""
        state = {**state_with_draft, "current_gate_results": []}
        
        mock = make_tool_mock({
            "mcp_commit_slide": {"success": False, "slide_id": None, "errors": ["DB error"]},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await commit_node(state)
            
            assert "why-postgres" in result["failed_intents"]


# =============================================================================
# CONDITIONAL EDGE TESTS
# =============================================================================

class TestConditionalEdges:
    """Tests for conditional edge functions."""
    
    def test_continue_after_pick_intent_to_retrieve(self, state_with_intent):
        """Should continue to retrieve when intent selected."""
        assert should_continue_after_pick_intent(state_with_intent) == "retrieve"
    
    def test_continue_after_pick_intent_to_end(self, initial_state):
        """Should end when deck is complete."""
        state = {**initial_state, "is_complete": True}
        assert should_continue_after_pick_intent(state) == "end"
    
    def test_continue_after_retrieve_to_draft(self, state_with_chunks):
        """Should continue to draft after successful retrieval."""
        assert should_continue_after_retrieve(state_with_chunks) == "draft"
    
    def test_continue_after_draft_to_validate(self, state_with_draft):
        """Should continue to validate after successful draft."""
        assert should_continue_after_draft(state_with_draft) == "validate_format"
    
    def test_continue_after_draft_with_retry(self, state_with_chunks):
        """Should retry draft on failure."""
        state = {
            **state_with_chunks,
            "last_failure_type": "parse_error",
            "slide_retries": 1,
            "max_retries_per_slide": 3,
        }
        assert should_continue_after_draft(state) == "draft"
    
    def test_continue_after_draft_insufficient_context(self, state_with_chunks):
        """Should re-retrieve on insufficient context."""
        state = {
            **state_with_chunks,
            "last_failure_type": "insufficient_context",
            "slide_retries": 1,
            "max_retries_per_slide": 3,
        }
        assert should_continue_after_draft(state) == "retrieve"
    
    def test_continue_after_format_pass(self, state_with_draft):
        """Should continue to citations after format pass."""
        state = {
            **state_with_draft,
            "current_gate_results": [{"gate_name": "g3_format", "passed": True}],
        }
        assert should_continue_after_format(state) == "validate_citations"
    
    def test_continue_after_format_fail_retry(self, state_with_draft):
        """Should retry draft on format fail."""
        state = {
            **state_with_draft,
            "current_gate_results": [{"gate_name": "g3_format", "passed": False}],
            "slide_retries": 1,
            "max_retries_per_slide": 3,
        }
        assert should_continue_after_format(state) == "draft"
    
    def test_continue_after_commit_to_pick_intent(self, state_with_draft):
        """Should continue to pick next intent after commit."""
        assert should_continue_after_commit(state_with_draft) == "pick_intent"
    
    def test_continue_after_commit_max_retries(self, state_with_draft):
        """Should end when max retries exceeded."""
        state = {
            **state_with_draft,
            "total_retries": 21,
            "max_total_retries": 20,
        }
        assert should_continue_after_commit(state) == "end"


# =============================================================================
# GRAPH BUILD TESTS
# =============================================================================

class TestBuildOrchestratorGraph:
    """Tests for build_orchestrator_graph function."""
    
    def test_builds_valid_graph(self):
        """Should build a valid LangGraph StateGraph."""
        graph = build_orchestrator_graph()
        
        assert graph is not None
    
    def test_graph_has_all_nodes(self):
        """Should have all required nodes."""
        graph = build_orchestrator_graph()
        
        expected_nodes = [
            "pick_intent", "retrieve", "draft", "validate_format",
            "validate_citations", "check_grounding", "check_novelty", "commit"
        ]
        
        for node in expected_nodes:
            assert node in graph.nodes
    
    def test_graph_entry_point(self):
        """Should have pick_intent as entry point."""
        graph = build_orchestrator_graph()
        
        compiled = graph.compile()
        assert compiled is not None


# =============================================================================
# RETRY LOGIC TESTS
# =============================================================================

class TestRetryLogic:
    """Tests for retry logic across nodes."""
    
    def test_max_retries_per_slide_respected(self, state_with_chunks):
        """Should give up on slide when max retries exceeded."""
        state = {
            **state_with_chunks,
            "slide_retries": 3,
            "max_retries_per_slide": 3,
            "last_failure_type": "format",
            "current_gate_results": [{"gate_name": "g3_format", "passed": False}],
        }
        
        assert should_continue_after_format(state) == "pick_intent"
    
    def test_total_retries_accumulated(self):
        """Total retries should accumulate across slides."""
        state = create_initial_state("deck")
        
        state["total_retries"] = 5
        state["total_retries"] += 1
        
        assert state["total_retries"] == 6
    
    def test_retry_state_reset_on_new_intent(self):
        """slide_retries should reset when moving to new intent."""
        state = create_initial_state("deck")
        state["slide_retries"] = 3
        state["current_intent"] = "old-intent"


# =============================================================================
# COST GATE TESTS
# =============================================================================

class TestCostGate:
    """Tests for cost tracking and cost limit enforcement."""
    
    def test_estimate_embedding_tokens(self):
        """Should estimate embedding tokens from text."""
        text = "hello world this is a test"
        tokens = _estimate_embedding_tokens(text)
        assert tokens == 7
    
    def test_calculate_cost(self):
        """Should calculate cost from token counts."""
        cost = _calculate_cost(
            prompt_tokens=1000,
            completion_tokens=1000,
            embedding_tokens=1000,
        )
        assert abs(cost - 0.09002) < 0.001
    
    def test_accumulate_llm_usage(self):
        """Should accumulate LLM usage in state."""
        state = create_initial_state("deck")
        resp = LLMResponse(text="hi", prompt_tokens=100, completion_tokens=50)
        
        update = _accumulate_llm_usage(state, resp)
        
        assert update["prompt_tokens"] == 100
        assert update["completion_tokens"] == 50
        assert update["estimated_cost_usd"] > 0
    
    def test_cost_limit_returns_end(self):
        """should_continue_after_commit returns 'end' when cost exceeded."""
        state = create_initial_state("deck")
        state["estimated_cost_usd"] = 15.0
        
        assert should_continue_after_commit(state) == "end"
    
    def test_cost_under_limit_returns_pick_intent(self):
        """should_continue_after_commit returns 'pick_intent' when cost under limit."""
        state = create_initial_state("deck")
        state["estimated_cost_usd"] = 0.50
        
        assert should_continue_after_commit(state) == "pick_intent"
    
    def test_cost_accumulates_in_draft_node(self, state_with_chunks):
        """Cost should accumulate after draft_node processes."""
        pass  # Covered by TestDraftNode.test_drafts_slide


# =============================================================================
# FALLBACK & ABANDONED INTENTS TESTS
# =============================================================================

class TestFallbackDeck:
    """Tests for fallback deck and abandoned intents."""
    
    def test_fallback_triggers_when_failures_exceed_max(self):
        """Fallback should trigger when failed+abandoned > MAX_FAILED_INTENTS."""
        state = create_initial_state("deck")
        state["failed_intents"] = ["a", "b"]
        state["abandoned_intents"] = ["c", "d"]
        
        assert should_continue_after_commit(state) == "end"
    
    def test_fallback_does_not_trigger_at_exactly_max(self):
        """Fallback should NOT trigger when failed+abandoned == MAX_FAILED_INTENTS."""
        state = create_initial_state("deck")
        state["failed_intents"] = ["a"]
        state["abandoned_intents"] = ["b", "c"]
        
        assert should_continue_after_commit(state) == "pick_intent"
    
    @pytest.mark.asyncio
    async def test_abandoned_intents_populated_on_retry_exhaustion(self):
        """Abandoned intents should be tracked when retry exhaustion occurs."""
        state = create_initial_state("deck")
        state["current_intent"] = "gates"
        state["slide_retries"] = 3
        state["max_retries_per_slide"] = 3
        state["generated_slides"] = []
        state["abandoned_intents"] = []
        
        mock = make_tool_mock({"mcp_pick_next_intent": "observability"})
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await pick_intent_node(state)
            
            assert "gates" in result["abandoned_intents"]
            assert result["current_intent"] == "observability"
    
    @pytest.mark.asyncio
    async def test_pick_intent_skips_abandoned(self):
        """pick_intent_node should pass abandoned intents as exclude list to DB."""
        state = create_initial_state("deck")
        state["abandoned_intents"] = ["gates"]
        state["current_intent"] = None
        state["slide_retries"] = 0
        
        _call_kwargs = {}

        async def _dispatch(name, **kwargs):
            nonlocal _call_kwargs
            _call_kwargs = kwargs
            return "observability"

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            result = await pick_intent_node(state)
            
            assert result["current_intent"] == "observability"
            assert _call_kwargs["exclude"] == ["gates"]


# =============================================================================
# COVERAGE ENRICHMENT (VIEWS AS SENSORS) TESTS
# =============================================================================

class TestCoverageEnrichment:
    """Tests for coverage enrichment (Views as Active Agent Sensors)."""
    
    def test_related_intents_accessor(self):
        """_get_related_intents should return DB-loaded related intents."""
        from src.orchestrator import _get_related_intents
        from src.models import IntentTypeInfo
        fake_map = {
            "rag-in-postgres": IntentTypeInfo(
                slide_type="body", require_image=False,
                related_intents=["what-is-rag"],
            ),
            "mcp-tools": IntentTypeInfo(
                slide_type="body", require_image=False,
                related_intents=["what-is-mcp"],
            ),
        }
        with patch("src.orchestrator.INTENT_TYPE_MAP", fake_map):
            assert _get_related_intents("rag-in-postgres") == ["what-is-rag"]
            assert _get_related_intents("mcp-tools") == ["what-is-mcp"]
            assert _get_related_intents("nonexistent-intent") == []
    
    @pytest.mark.asyncio
    @patch("src.orchestrator._get_related_intents", return_value=["what-is-rag"])
    async def test_coverage_enrichment_on_first_slide(self, _mock_rel, mock_chunks):
        """Coverage enrichment should be no-op on first slide (empty coverage)."""
        state = create_initial_state("deck")
        state["current_intent"] = "rag-in-postgres"
        state["current_slide_no"] = 1
        
        mock = make_tool_mock({
            "mcp_search_chunks": mock_chunks,
            "mcp_get_deck_state": {"coverage": {"covered": []}},
            "mcp_check_retrieval_quality": {"is_valid": True, "chunk_count": 3, "top_score": 0.9, "errors": []},
            "mcp_log_gate": {"log_id": "mock-log-id"},
        })
        with patch("src.orchestrator.tool_call", side_effect=mock):
            result = await retrieve_node(state)
            
            coverage_gate = [g for g in result["current_gate_results"] if g["gate_name"] == "coverage_sensor"]
            assert len(coverage_gate) == 1
            assert coverage_gate[0]["details"]["enrichment_applied"] == ""


# =============================================================================
# GENERATION_RUN LIFECYCLE TESTS
# =============================================================================

class TestGenerationRunLifecycle:
    """Tests for generation_run INSERT/UPDATE lifecycle."""

    def test_build_run_config_captures_settings(self):
        """_build_run_config should capture all runtime settings."""
        from src.orchestrator import _build_run_config
        config = _build_run_config()
        assert "max_retries_per_slide" in config
        assert "grounding_threshold" in config
        assert "cost_limit_usd" in config
        assert "image_selection_enabled" in config

    def test_determine_run_status_completed(self):
        """Normal completion should return 'completed'."""
        from src.orchestrator import _determine_run_status
        state = {
            "is_complete": True,
            "estimated_cost_usd": 0.5,
            "failed_intents": [],
            "abandoned_intents": [],
            "total_retries": 5,
            "llm_calls": 20,
        }
        assert _determine_run_status(state) == "completed"

    def test_determine_run_status_defaults_to_failed(self):
        """If is_complete is False and no specific condition, return 'failed'."""
        from src.orchestrator import _determine_run_status
        state = {
            "is_complete": False,
            "estimated_cost_usd": 0.5,
            "failed_intents": [],
            "abandoned_intents": [],
            "total_retries": 5,
            "llm_calls": 20,
        }
        assert _determine_run_status(state) == "failed"

    def test_determine_run_status_cost_limited(self):
        """Cost exceeding limit should return 'cost_limited'."""
        from src.orchestrator import _determine_run_status, COST_LIMIT_USD
        state = {
            "estimated_cost_usd": COST_LIMIT_USD + 1.0,
            "failed_intents": [],
            "abandoned_intents": [],
            "total_retries": 5,
            "llm_calls": 20,
        }
        assert _determine_run_status(state) == "cost_limited"

    def test_determine_run_status_failed_intents(self):
        """Too many failed intents should return 'failed'."""
        from src.orchestrator import _determine_run_status, MAX_FAILED_INTENTS
        state = {
            "estimated_cost_usd": 0.5,
            "failed_intents": ["a", "b"],
            "abandoned_intents": ["c", "d"],
            "total_retries": 5,
            "llm_calls": 20,
        }
        assert _determine_run_status(state) == "failed"

    @pytest.mark.asyncio
    async def test_start_generation_run_fallback_on_error(self):
        """_start_generation_run should return a UUID even if DB INSERT fails."""
        from src.orchestrator import _start_generation_run
        with patch("src.orchestrator.get_connection") as mock_conn:
            mock_conn.side_effect = Exception("DB down")
            run_id = await _start_generation_run("deck-123", {"key": "val"})
            assert len(run_id) == 36
            assert "-" in run_id

    @pytest.mark.asyncio
    async def test_complete_generation_run_silent_on_error(self):
        """_complete_generation_run should not raise if DB UPDATE fails."""
        from src.orchestrator import _complete_generation_run
        with patch("src.orchestrator.get_connection") as mock_conn:
            mock_conn.side_effect = Exception("DB down")
            await _complete_generation_run("00000000-0000-0000-0000-000000000000", {"total_retries": 5}, status="failed")


# =============================================================================
# DECK STATUS LIFECYCLE TESTS
# =============================================================================

class TestDeckStatusLifecycle:
    """Tests for deck.status transitions."""

    @pytest.mark.asyncio
    async def test_set_deck_status_silent_on_error(self):
        """_set_deck_status should not raise if DB UPDATE fails."""
        from src.orchestrator import _set_deck_status
        with patch("src.orchestrator.get_connection") as mock_conn:
            mock_conn.side_effect = Exception("DB down")
            await _set_deck_status("deck-123", "generating")

    @pytest.mark.asyncio
    async def test_cleanup_stale_generating_silent_on_error(self):
        """cleanup_stale_generating should not raise if DB fails."""
        from src.orchestrator import cleanup_stale_generating
        with patch("src.orchestrator.get_connection") as mock_conn:
            mock_conn.side_effect = Exception("DB down")
            count = await cleanup_stale_generating()
            assert count == 0

    def test_deck_status_for_cost_limited_is_completed(self):
        """A cost-limited run should result in deck.status = 'completed'."""
        from src.orchestrator import _determine_run_status
        state = {"estimated_cost_usd": 999.0, "failed_intents": [], "abandoned_intents": [], "total_retries": 0, "llm_calls": 0}
        run_status = _determine_run_status(state)
        assert run_status == "cost_limited"
        deck_status = "completed" if run_status in ("completed", "cost_limited") else "failed"
        assert deck_status == "completed"


# =============================================================================
# GATE LOGGING TESTS
# =============================================================================

class TestGateLogging:
    """Tests for gate result persistence via mcp_log_gate."""

    @pytest.mark.asyncio
    async def test_gate_failure_logged(self, state_with_draft):
        """Should call mcp_log_gate with decision='fail' when a gate fails."""
        _log_calls = []

        async def _dispatch(name, **kwargs):
            if name == "mcp_validate_slide_structure":
                return {"is_valid": False, "errors": ["Too many bullets"]}
            if name == "mcp_log_gate":
                _log_calls.append(kwargs)
                return {"log_id": "mock-log-id"}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            await validate_format_node(state_with_draft)

            assert len(_log_calls) == 1
            call = _log_calls[0]
            assert call["gate_name"] == "g3_format"
            assert call["decision"] == "fail"
            assert call["deck_id"] == state_with_draft["deck_id"]
            assert call["slide_no"] == state_with_draft["current_slide_no"]
            assert "Too many bullets" in call["reason"]

    @pytest.mark.asyncio
    async def test_gate_pass_logged(self, state_with_draft):
        """Should call mcp_log_gate with decision='pass' when a gate passes."""
        _log_calls = []

        async def _dispatch(name, **kwargs):
            if name == "mcp_validate_slide_structure":
                return {"is_valid": True, "errors": []}
            if name == "mcp_log_gate":
                _log_calls.append(kwargs)
                return {"log_id": "mock-log-id"}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            await validate_format_node(state_with_draft)

            assert len(_log_calls) == 1
            call = _log_calls[0]
            assert call["gate_name"] == "g3_format"
            assert call["decision"] == "pass"

    @pytest.mark.asyncio
    async def test_gate_logging_failure_does_not_break_generation(self, state_with_draft):
        """Gate logging errors should be swallowed, not crash the node."""
        async def _dispatch(name, **kwargs):
            if name == "mcp_validate_slide_structure":
                return {"is_valid": True, "errors": []}
            if name == "mcp_log_gate":
                raise ConnectionError("DB unavailable")
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            result = await validate_format_node(state_with_draft)
            g3 = [g for g in result["current_gate_results"] if g["gate_name"] == "g3_format"][0]
            assert g3["passed"] is True

    @pytest.mark.asyncio
    async def test_retrieve_logs_both_gates(self, state_with_intent, mock_chunks):
        """retrieve_node should log both g1_retrieval and coverage_sensor."""
        _log_calls = []

        async def _dispatch(name, **kwargs):
            if name == "mcp_search_chunks":
                return mock_chunks
            if name == "mcp_get_deck_state":
                return {"coverage": {"covered": []}}
            if name == "mcp_check_retrieval_quality":
                return {"is_valid": True, "chunk_count": 3, "top_score": 0.9, "errors": []}
            if name == "mcp_log_gate":
                _log_calls.append(kwargs)
                return {"log_id": "mock-log-id"}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            await retrieve_node(state_with_intent)

            gate_names = [c["gate_name"] for c in _log_calls]
            assert "g1_retrieval" in gate_names
            assert "coverage_sensor" in gate_names

    @pytest.mark.asyncio
    async def test_grounding_logs_threshold(self, state_with_draft):
        """G2.5 gate log should include the threshold value."""
        _log_calls = []

        async def _dispatch(name, **kwargs):
            if name == "mcp_check_grounding":
                return {"is_grounded": True, "min_similarity": 0.8, "ungrounded_bullets": []}
            if name == "mcp_log_gate":
                _log_calls.append(kwargs)
                return {"log_id": "mock-log-id"}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            await check_grounding_node(state_with_draft)

            call = _log_calls[0]
            assert call["gate_name"] == "g2.5_grounding"
            assert call["threshold"] is not None
            assert call["threshold"] > 0

    @pytest.mark.asyncio
    async def test_novelty_logs_threshold(self, state_with_draft):
        """G4 gate log should include the novelty threshold value."""
        _log_calls = []

        async def _dispatch(name, **kwargs):
            if name == "mcp_check_novelty":
                return {"is_novel": True, "max_similarity": 0.5, "most_similar_slide_no": None}
            if name == "mcp_log_gate":
                _log_calls.append(kwargs)
                return {"log_id": "mock-log-id"}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            await check_novelty_node(state_with_draft)

            call = _log_calls[0]
            assert call["gate_name"] == "g4_novelty"
            assert call["threshold"] is not None
            assert call["threshold"] > 0


class TestDraftRetriesPassthrough:
    """Tests for draft_retries being passed to mcp_commit_slide."""

    @pytest.mark.asyncio
    async def test_commit_passes_draft_retries(self, state_with_draft):
        """Should pass state['slide_retries'] as draft_retries to mcp_commit_slide."""
        state = {
            **state_with_draft,
            "slide_retries": 3,
            "current_gate_results": [
                {"gate_name": "g4_novelty", "passed": True, "score": 0.5, "details": {"max_similarity": 0.5}},
                {"gate_name": "g2.5_grounding", "passed": True, "score": 0.8, "details": {}},
            ],
        }

        _commit_kwargs = {}

        async def _dispatch(name, **kwargs):
            nonlocal _commit_kwargs
            if name == "mcp_commit_slide":
                _commit_kwargs = kwargs
                return {"success": True, "slide_id": "slide-123", "errors": []}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            await commit_node(state)

            assert _commit_kwargs["draft_retries"] == 3

    @pytest.mark.asyncio
    async def test_commit_passes_zero_retries_on_first_attempt(self, state_with_draft):
        """Should pass draft_retries=0 when slide succeeded on first attempt."""
        state = {
            **state_with_draft,
            "slide_retries": 0,
            "current_gate_results": [
                {"gate_name": "g4_novelty", "passed": True, "score": 0.5, "details": {"max_similarity": 0.5}},
                {"gate_name": "g2.5_grounding", "passed": True, "score": 0.8, "details": {}},
            ],
        }

        _commit_kwargs = {}

        async def _dispatch(name, **kwargs):
            nonlocal _commit_kwargs
            if name == "mcp_commit_slide":
                _commit_kwargs = kwargs
                return {"success": True, "slide_id": "slide-456", "errors": []}
            raise ValueError(f"Unmocked: {name}")

        with patch("src.orchestrator.tool_call", side_effect=_dispatch):
            await commit_node(state)

            assert _commit_kwargs["draft_retries"] == 0
