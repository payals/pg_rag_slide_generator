"""
Unit tests for LLM client (src/llm.py).

Tests prompt formatting, JSON parsing, and error handling.
Uses mocks to avoid actual OpenAI API calls.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import src.renderer as renderer_mod
import src.models as _models
from src.models import IntentTypeInfo
from src.llm import (
    LLMResponse,
    parse_slide_response,
    parse_queries_response,
    format_chunks_for_prompt,
    get_intent_metadata,
    strip_inline_citations,
    InsufficientContextError,
    ParseError,
    LLMError,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def _mock_renderer_init():
    """Ensure get_target_slides() works without a real DB."""
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


@pytest.fixture(autouse=True)
def _populate_llm_caches():
    """Seed SLIDE_TYPE_CONFIGS and PROMPT_TEMPLATES for unit tests."""
    fake_configs = {
        "bullets": {"prompt_schema": "Return valid JSON matching this schema:\n{{...}}", "content_fields": {}},
        "statement": {"prompt_schema": "Return valid JSON...", "content_fields": {}},
        "split": {"prompt_schema": "Return valid JSON...", "content_fields": {}},
        "flow": {"prompt_schema": "Return valid JSON...", "content_fields": {}},
        "code": {"prompt_schema": "Return valid JSON...", "content_fields": {}},
        "diagram": {"prompt_schema": "Return valid JSON...", "content_fields": {}},
    }
    fake_templates = {
        "slide_generation": {
            "system_prompt": "You are a technical slide writer.\n\n<context>\n{retrieved_chunks}\n</context>",
            "user_prompt": "Generate slide for intent: {intent}\nTitle: {suggested_title}\nRequirements: {requirements}\nSlide: {slide_no} of {total_slides}\nPrior: {prior_titles}",
        },
        "rewrite_format": {
            "system_prompt": "Rewrite to fix format.\n{output_schema}\n{failed_slide_spec}\n{validation_errors}\n{original_context}",
            "user_prompt": "Fix: {specific_issues}",
        },
        "rewrite_grounding": {
            "system_prompt": "Rewrite for grounding.\n{output_schema}\n{failed_slide_spec}\n{ungrounded_bullet_indices}\n{cited_chunks_content}",
            "user_prompt": "Fix bullets {ungrounded_indices}",
        },
        "rewrite_novelty": {
            "system_prompt": "Rewrite for novelty. Intent: {intent}\n{output_schema}\n{concepts_from_similar_slide}\n{failed_slide_spec}\n{most_similar_slide}\n{similarity_score}\n{retrieved_chunks}",
            "user_prompt": "Rewrite {intent} differently.\nExisting: {existing_focus}\nNew: {alternative_focus}",
        },
        "alternative_queries": {
            "system_prompt": "Generate queries for {intent}.\n{what_was_missing}\n{requirements}",
            "user_prompt": "Find content about: {missing_topic}",
        },
    }
    with patch("src.llm.SLIDE_TYPE_CONFIGS", fake_configs), \
         patch("src.llm.PROMPT_TEMPLATES", fake_templates):
        yield


@pytest.fixture
def valid_slide_response():
    """Valid slide response JSON."""
    return json.dumps({
        "title": "Why Postgres for AI Workloads",
        "intent": "why-postgres",
        "bullets": [
            "Postgres is battle-tested with 30+ years of production use",
            "Built-in ACID guarantees ensure data integrity",
            "Extensions like pgvector add AI capabilities"
        ],
        "speaker_notes": "This slide explains why Postgres is the right choice...",
        "citations": [
            {
                "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
                "doc_title": "Supabase Postgres AI",
                "relevance": "Discusses Postgres advantages"
            }
        ]
    })


@pytest.fixture
def insufficient_context_response():
    """Response indicating insufficient context."""
    return json.dumps({
        "error": "INSUFFICIENT_CONTEXT",
        "missing": "Details about specific vector database performance benchmarks"
    })


@pytest.fixture
def sample_chunks():
    """Sample retrieved chunks."""
    return [
        {
            "chunk_id": "550e8400-e29b-41d4-a716-446655440000",
            "doc_title": "Supabase Postgres AI",
            "content": "Postgres is a powerful database for AI workloads...",
            "trust_level": "high",
        },
        {
            "chunk_id": "550e8400-e29b-41d4-a716-446655440001",
            "doc_title": "pgvector Documentation",
            "content": "pgvector is a PostgreSQL extension for vector similarity search...",
            "trust_level": "high",
        },
    ]


# =============================================================================
# RESPONSE PARSING TESTS
# =============================================================================

class TestParseSlideResponse:
    """Tests for parse_slide_response function."""
    
    def test_parse_valid_response(self, valid_slide_response):
        """Should parse valid JSON response."""
        result = parse_slide_response(valid_slide_response)
        
        assert result["title"] == "Why Postgres for AI Workloads"
        assert result["intent"] == "why-postgres"
        assert len(result["bullets"]) == 3
        assert "speaker_notes" in result
        assert len(result["citations"]) == 1
    
    def test_parse_response_with_markdown_code_blocks(self, valid_slide_response):
        """Should strip markdown code blocks."""
        wrapped = f"```json\n{valid_slide_response}\n```"
        result = parse_slide_response(wrapped)
        
        assert result["title"] == "Why Postgres for AI Workloads"
    
    def test_parse_response_with_backticks_only(self, valid_slide_response):
        """Should strip backticks without json marker."""
        wrapped = f"```\n{valid_slide_response}\n```"
        result = parse_slide_response(wrapped)
        
        assert result["title"] == "Why Postgres for AI Workloads"
    
    def test_parse_insufficient_context_error(self, insufficient_context_response):
        """Should raise InsufficientContextError for INSUFFICIENT_CONTEXT response."""
        with pytest.raises(InsufficientContextError) as exc_info:
            parse_slide_response(insufficient_context_response)
        
        assert "vector database performance benchmarks" in exc_info.value.missing
    
    def test_parse_invalid_json(self):
        """Should raise ParseError for invalid JSON."""
        with pytest.raises(ParseError) as exc_info:
            parse_slide_response("not valid json {")
        
        assert "not valid json" in exc_info.value.raw_response
    
    def test_parse_missing_required_fields(self):
        """Should raise ParseError for missing required fields."""
        response = json.dumps({"title": "Test"})  # Missing intent and bullets
        
        with pytest.raises(ParseError) as exc_info:
            parse_slide_response(response)
        
        assert "Missing required fields" in exc_info.value.error
    
    def test_parse_generic_error_response(self):
        """Should raise LLMError for generic error response."""
        response = json.dumps({"error": "RATE_LIMIT", "message": "Too many requests"})
        
        with pytest.raises(LLMError) as exc_info:
            parse_slide_response(response)
        
        assert "RATE_LIMIT" in str(exc_info.value)
    
    def test_parse_whitespace_handling(self, valid_slide_response):
        """Should handle extra whitespace."""
        padded = f"\n\n  {valid_slide_response}  \n\n"
        result = parse_slide_response(padded)
        
        assert result["title"] == "Why Postgres for AI Workloads"


class TestStripInlineCitations:
    """Tests for inline citation UUID stripping."""

    def test_strips_single_uuid(self):
        text = "Unified stack [8e24e3a6-5d26-4c9b-99a3-3d542df9d554]"
        assert strip_inline_citations(text) == "Unified stack"

    def test_strips_multiple_uuids(self):
        text = "Bullet text [aaaa1111-2222-3333-4444-555566667777][bbbb1111-2222-3333-4444-555566667777]"
        assert strip_inline_citations(text) == "Bullet text"

    def test_no_uuids_unchanged(self):
        text = "No citations here"
        assert strip_inline_citations(text) == "No citations here"

    def test_mid_text_uuid(self):
        text = "First [aaaa1111-2222-3333-4444-555566667777] second"
        assert strip_inline_citations(text) == "First second"

    def test_parse_strips_bullets(self):
        response = json.dumps({
            "title": "Test",
            "intent": "problem",
            "bullets": [
                "Point one [aaaa1111-2222-3333-4444-555566667777]",
                "Point two [bbbb1111-2222-3333-4444-555566667777][cccc1111-2222-3333-4444-555566667777]",
            ],
            "speaker_notes": "Notes [dddd1111-2222-3333-4444-555566667777]",
            "citations": [{"chunk_id": "aaaa1111-2222-3333-4444-555566667777"}],
        })
        result = parse_slide_response(response)
        assert result["bullets"] == ["Point one", "Point two"]
        assert result["speaker_notes"] == "Notes"
        assert result["citations"][0]["chunk_id"] == "aaaa1111-2222-3333-4444-555566667777"

    def test_parse_strips_content_data_items(self):
        response = json.dumps({
            "title": "Compare",
            "intent": "comparison",
            "slide_type": "split",
            "content_data": {
                "left_title": "Postgres",
                "right_title": "Others",
                "left_items": ["Item A [aaaa1111-2222-3333-4444-555566667777]"],
                "right_items": ["Item B [bbbb1111-2222-3333-4444-555566667777]"],
            },
            "speaker_notes": "Notes",
            "citations": [],
        })
        result = parse_slide_response(response)
        assert result["content_data"]["left_items"] == ["Item A"]
        assert result["content_data"]["right_items"] == ["Item B"]


class TestCleanSlideTextEquivalence:
    """Verify refactored _clean_slide_text produces identical output."""

    def test_content_data_all_types_cleaned(self):
        """Ensure all content_data field types have citations stripped."""
        from src.llm import _clean_slide_text

        data = {
            "title": "Test",
            "bullets": ["Bullet [8e24e3a6-1234-5678-9abc-def012345678]"],
            "speaker_notes": "Notes [7145eea4-1234-5678-9abc-def012345678]",
            "content_data": {
                "statement": "Stmt [abcd1234-1234-5678-9abc-def012345678]",
                "subtitle": "Sub [abcd1234-1234-5678-9abc-def012345678]",
                "caption": "Cap [abcd1234-1234-5678-9abc-def012345678]",
                "code_block": "SELECT 1; [abcd1234-1234-5678-9abc-def012345678]",
                "callouts": ["Call [abcd1234-1234-5678-9abc-def012345678]"],
                "explain_bullets": ["Explain [abcd1234-1234-5678-9abc-def012345678]"],
                "left_items": ["Left [abcd1234-1234-5678-9abc-def012345678]"],
                "right_items": ["Right [abcd1234-1234-5678-9abc-def012345678]"],
                "steps": [
                    {
                        "label": "Label [abcd1234-1234-5678-9abc-def012345678]",
                        "caption": "Step cap [abcd1234-1234-5678-9abc-def012345678]",
                    }
                ],
            },
        }
        result = _clean_slide_text(data)

        assert result["bullets"] == ["Bullet"]
        assert result["speaker_notes"] == "Notes"
        cd = result["content_data"]
        assert cd["statement"] == "Stmt"
        assert cd["subtitle"] == "Sub"
        assert cd["caption"] == "Cap"
        assert cd["code_block"] == "SELECT 1;"
        assert cd["callouts"] == ["Call"]
        assert cd["explain_bullets"] == ["Explain"]
        assert cd["left_items"] == ["Left"]
        assert cd["right_items"] == ["Right"]
        assert cd["steps"][0]["label"] == "Label"
        assert cd["steps"][0]["caption"] == "Step cap"


class TestParseQueriesResponse:
    """Tests for parse_queries_response function."""
    
    def test_parse_valid_queries(self):
        """Should parse valid queries JSON."""
        response = json.dumps({
            "queries": [
                "Postgres vector search performance",
                "pgvector vs Pinecone benchmark",
                "AI database comparison"
            ]
        })
        
        result = parse_queries_response(response)
        
        assert len(result) == 3
        assert "Postgres vector search performance" in result
    
    def test_parse_queries_with_code_blocks(self):
        """Should strip code blocks from queries response."""
        response = "```json\n" + json.dumps({"queries": ["query1", "query2"]}) + "\n```"
        
        result = parse_queries_response(response)
        
        assert len(result) == 2
    
    def test_parse_queries_fallback_to_plain_text(self):
        """Should extract queries from plain text if JSON fails."""
        response = """
        - Postgres AI capabilities
        - Vector database comparison
        - pgvector performance
        """
        
        result = parse_queries_response(response)
        
        assert len(result) == 3
        assert "Postgres AI capabilities" in result
    
    def test_parse_queries_empty_response(self):
        """Should handle empty response gracefully."""
        result = parse_queries_response("")
        
        assert result == []
    
    def test_parse_queries_max_three(self):
        """Should return max 3 queries from plain text."""
        response = """
        - Query 1
        - Query 2
        - Query 3
        - Query 4
        - Query 5
        """
        
        result = parse_queries_response(response)
        
        assert len(result) == 3


# =============================================================================
# PROMPT FORMATTING TESTS
# =============================================================================

class TestFormatChunksForPrompt:
    """Tests for format_chunks_for_prompt function."""
    
    def test_format_single_chunk(self, sample_chunks):
        """Should format single chunk correctly."""
        result = format_chunks_for_prompt([sample_chunks[0]])
        
        assert '<chunk id="550e8400-e29b-41d4-a716-446655440000">' in result
        assert "<source>Supabase Postgres AI</source>" in result
        assert "<trust_level>high</trust_level>" in result
        assert "Postgres is a powerful database" in result
    
    def test_format_multiple_chunks(self, sample_chunks):
        """Should format multiple chunks."""
        result = format_chunks_for_prompt(sample_chunks)
        
        assert "550e8400-e29b-41d4-a716-446655440000" in result
        assert "550e8400-e29b-41d4-a716-446655440001" in result
        assert "Supabase Postgres AI" in result
        assert "pgvector Documentation" in result
    
    def test_format_empty_chunks(self):
        """Should handle empty chunks list."""
        result = format_chunks_for_prompt([])
        
        assert result == ""
    
    def test_format_chunk_missing_fields(self):
        """Should handle chunks with missing optional fields."""
        chunk = {
            "chunk_id": "test-id",
            "content": "Test content",
        }
        
        result = format_chunks_for_prompt([chunk])
        
        assert 'id="test-id"' in result
        assert "Test content" in result
        assert "Unknown" in result  # Default for missing doc_title


# =============================================================================
# INTENT METADATA TESTS
# =============================================================================

class TestGetIntentMetadata:
    """Tests for get_intent_metadata function."""

    @pytest.fixture(autouse=True)
    def _populate_intent_map(self):
        """Seed INTENT_TYPE_MAP so get_intent_metadata reads DB-like data."""
        from src.models import IntentTypeInfo

        fake_map = {}
        intents_config = [
            ("title", "bullets", False, 0, "Postgres as AI Application Server",
             "Opening slide with talk title, speaker name, event, date", False),
            ("problem", "bullets", True, 1, "The AI Infrastructure Problem",
             "2-3 bullets on AI infrastructure pain points: database sprawl, lack of transactions, audit gaps, safety concerns", True),
            ("why-postgres", "bullets", True, 2, "Why Postgres for AI Workloads",
             "2-3 bullets on why Postgres: mature, ACID, extensions, single source of truth, community", True),
            ("comparison", "split", True, 3, "Postgres vs Vector Databases",
             "Two-column comparison: left_title + 2-3 items vs right_title + 2-3 items. Postgres strengths vs tradeoffs.", True),
            ("capabilities", "bullets", True, 4, "Postgres AI Primitives",
             "3 bullets, one per AI primitive built into or added to Postgres.", True),
            ("thesis", "statement", False, 5, "The Database IS the Control Plane",
             "One statement sentence (8-90 chars) + optional subtitle.", True),
            ("schema-security", "bullets", True, 6, "Schema Design & Security",
             "2-3 bullets on defense-in-depth.", True),
            ("architecture", "diagram", True, 7, "System Architecture",
             "Diagram with callouts and a caption.", True),
            ("what-is-rag", "diagram", True, 8, "What is RAG?",
             "Diagram with callouts and a caption.", True),
            ("rag-in-postgres", "code", True, 9, "RAG Inside Postgres",
             "SQL code snippet + explanation bullets.", True),
            ("advanced-retrieval", "split", False, 10, "Beyond Vector Search",
             "Split layout comparing two retrieval stages. Left: RRF inside Postgres. Right: cross-encoder reranking in Python.", True),
            ("what-is-mcp", "diagram", True, 11, "What is MCP?",
             "Diagram with callouts and a caption.", True),
            ("mcp-tools", "code", True, 12, "Typed Tools, Not Raw SQL",
             "Code block + explanation bullets.", True),
            ("gates", "flow", True, 13, "Control Gates & Validation",
             "Pipeline flow: 4-7 steps.", True),
            ("observability", "code", True, 14, "Observable AI with SQL",
             "SQL code snippet + explanation bullets.", True),
            ("what-we-built", "bullets", True, 15, "What We Built",
             "Recap: slide generator using this architecture.", True),
            ("takeaways", "bullets", True, 16, "Key Takeaways",
             "2-3 memorable points.", True),
            ("thanks", "bullets", False, 17, "Thank You & Questions",
             "Closing slide with contact info and resources", False),
        ]
        for intent, stype, req_img, order, title, reqs, gen in intents_config:
            fake_map[intent] = IntentTypeInfo(
                slide_type=stype, require_image=req_img, sort_order=order,
                suggested_title=title, requirements=reqs, is_generatable=gen,
            )

        with patch("src.llm.INTENT_TYPE_MAP", fake_map):
            yield

    def test_get_known_intent(self):
        """Should return metadata for known intent."""
        result = get_intent_metadata("why-postgres")
        
        assert result["suggested_title"] == "Why Postgres for AI Workloads"
        assert "ACID" in result["requirements"] or "mature" in result["requirements"]
    
    def test_get_unknown_intent(self):
        """Should return default metadata for unknown intent."""
        result = get_intent_metadata("unknown-intent")
        
        assert "Unknown Intent" in result["suggested_title"]
        assert "Generate content" in result["requirements"]
    
    def test_all_intents_have_metadata(self):
        """All slide intents should have defined metadata."""
        expected_intents = [
            "title", "problem", "why-postgres", "comparison", "capabilities",
            "thesis", "schema-security", "architecture", "what-is-rag",
            "rag-in-postgres", "what-is-mcp", "mcp-tools", "gates",
            "observability", "what-we-built", "takeaways", "thanks"
        ]
        
        for intent in expected_intents:
            metadata = get_intent_metadata(intent)
            assert "suggested_title" in metadata
            assert "requirements" in metadata
            assert metadata["requirements"] != "Generate content for this slide intent", \
                f"Intent '{intent}' has default requirements — not loaded from INTENT_TYPE_MAP"


# =============================================================================
# ERROR CLASS TESTS
# =============================================================================

class TestErrorClasses:
    """Tests for error classes."""
    
    def test_insufficient_context_error(self):
        """Should store missing info."""
        error = InsufficientContextError("benchmark data")
        
        assert error.missing == "benchmark data"
        assert "benchmark data" in str(error)
    
    def test_parse_error(self):
        """Should store raw response and error."""
        error = ParseError("raw content", "JSON decode error")
        
        assert error.raw_response == "raw content"
        assert error.error == "JSON decode error"
        assert "JSON decode error" in str(error)
    
    def test_llm_error_base(self):
        """Should work as base exception."""
        error = LLMError("Generic error")
        
        assert "Generic error" in str(error)


# =============================================================================
# LLM CALL TESTS (with mocks)
# =============================================================================

class TestDraftSlide:
    """Tests for draft_slide function."""
    
    @pytest.mark.asyncio
    async def test_draft_slide_success(self, sample_chunks, valid_slide_response):
        """Should return parsed slide spec and LLMResponse on success."""
        mock_llm_response = LLMResponse(text=valid_slide_response, prompt_tokens=100, completion_tokens=200)
        
        with patch("src.llm.call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            
            from src.llm import draft_slide
            
            result, llm_resp = await draft_slide(
                intent="why-postgres",
                chunks=sample_chunks,
                slide_no=3,
                total_slides=14,
                prior_titles=["Title Slide", "The Problem"],
            )
            
            assert result["title"] == "Why Postgres for AI Workloads"
            assert result["intent"] == "why-postgres"
            assert len(result["bullets"]) == 3
            assert llm_resp.prompt_tokens == 100
            assert llm_resp.completion_tokens == 200
            
            # Verify call_llm was called with correct prompts
            mock_call.assert_called_once()
            args = mock_call.call_args
            assert "why-postgres" in args[0][1]  # User prompt contains intent
            assert "slide" in args[0][1].lower()  # User prompt mentions slide
    
    @pytest.mark.asyncio
    async def test_draft_slide_insufficient_context(self, sample_chunks, insufficient_context_response):
        """Should raise InsufficientContextError."""
        mock_llm_response = LLMResponse(text=insufficient_context_response, prompt_tokens=50, completion_tokens=20)
        
        with patch("src.llm.call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            
            from src.llm import draft_slide
            
            with pytest.raises(InsufficientContextError):
                await draft_slide(
                    intent="comparison",
                    chunks=sample_chunks,
                    slide_no=4,
                )


class TestGenerateAlternativeQueries:
    """Tests for generate_alternative_queries function."""
    
    @pytest.mark.asyncio
    async def test_generate_queries(self):
        """Should generate alternative queries and return LLMResponse."""
        response_text = json.dumps({
            "queries": ["query1", "query2", "query3"]
        })
        mock_llm_response = LLMResponse(text=response_text, prompt_tokens=30, completion_tokens=40)
        
        with patch("src.llm.call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            
            from src.llm import generate_alternative_queries
            
            result, llm_resp = await generate_alternative_queries(
                intent="comparison",
                missing_info="benchmark data",
            )
            
            assert len(result) == 3
            assert llm_resp.prompt_tokens == 30
            mock_call.assert_called_once()


class TestRewriteFunctions:
    """Tests for rewrite functions."""
    
    @pytest.mark.asyncio
    async def test_rewrite_slide_format(self, sample_chunks, valid_slide_response):
        """Should call LLM with format rewrite prompt and return LLMResponse."""
        mock_llm_response = LLMResponse(text=valid_slide_response, prompt_tokens=80, completion_tokens=150)
        
        with patch("src.llm.call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            
            from src.llm import rewrite_slide_format
            
            failed_spec = {
                "title": "Test",
                "intent": "why-postgres",
                "bullets": ["Too long bullet " * 10],  # Invalid
            }
            
            result, llm_resp = await rewrite_slide_format(
                failed_slide_spec=failed_spec,
                validation_errors=["Bullet too long"],
                original_chunks=sample_chunks,
            )
            
            assert "title" in result
            assert llm_resp.prompt_tokens == 80
            mock_call.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_rewrite_slide_grounding(self, sample_chunks, valid_slide_response):
        """Should call LLM with grounding rewrite prompt."""
        mock_llm_response = LLMResponse(text=valid_slide_response, prompt_tokens=90, completion_tokens=160)
        
        with patch("src.llm.call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            
            from src.llm import rewrite_slide_grounding
            
            failed_spec = {
                "title": "Test",
                "intent": "why-postgres",
                "bullets": ["Ungrounded statement"],
            }
            
            result, llm_resp = await rewrite_slide_grounding(
                failed_slide_spec=failed_spec,
                ungrounded_bullets=[0],
                cited_chunks=sample_chunks,
            )
            
            assert "title" in result
    
    @pytest.mark.asyncio
    async def test_rewrite_slide_novelty(self, sample_chunks, valid_slide_response):
        """Should call LLM with novelty rewrite prompt."""
        mock_llm_response = LLMResponse(text=valid_slide_response, prompt_tokens=85, completion_tokens=155)
        
        with patch("src.llm.call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = mock_llm_response
            
            from src.llm import rewrite_slide_novelty
            
            failed_spec = {
                "title": "Test",
                "intent": "why-postgres",
                "bullets": ["Similar bullet"],
            }
            
            similar_slide = {
                "title": "Similar Slide",
                "bullets": ["Similar bullet", "Another point"],
            }
            
            result, llm_resp = await rewrite_slide_novelty(
                failed_slide_spec=failed_spec,
                most_similar_slide=similar_slide,
                similarity_score=0.9,
                chunks=sample_chunks,
            )
            
            assert "title" in result


# =============================================================================
# LLM RESPONSE DATACLASS TESTS
# =============================================================================

class TestLLMResponse:
    """Tests for LLMResponse dataclass."""
    
    def test_creates_llm_response(self):
        """Should create LLMResponse with all fields."""
        resp = LLMResponse(text="hello", prompt_tokens=10, completion_tokens=20)
        
        assert resp.text == "hello"
        assert resp.prompt_tokens == 10
        assert resp.completion_tokens == 20
    
    def test_llm_response_zero_tokens(self):
        """Should handle zero token counts."""
        resp = LLMResponse(text="", prompt_tokens=0, completion_tokens=0)
        
        assert resp.prompt_tokens == 0
        assert resp.completion_tokens == 0
