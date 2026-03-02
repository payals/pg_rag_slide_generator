"""
Unit tests for MCP Server tools.

Tests tool input validation, error handling, and mock database interactions.
Each tool is tested in isolation with mocked dependencies.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from src import config


# -----------------------------------------------------------------------------
# Test Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_conn():
    """Mock asyncpg connection."""
    conn = AsyncMock()
    conn.fetch = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetchval = AsyncMock()
    conn.execute = AsyncMock()
    return conn


@pytest.fixture
def mock_openai():
    """Mock OpenAI client that returns deterministic embeddings."""
    client = AsyncMock()
    
    # Create mock embedding response
    def create_embedding(*args, **kwargs):
        mock_response = MagicMock()
        mock_data = MagicMock()
        # Return a simple deterministic embedding
        mock_data.embedding = [0.1] * 1536
        mock_response.data = [mock_data]
        return mock_response
    
    client.embeddings.create = AsyncMock(side_effect=create_embedding)
    return client


@pytest.fixture
def sample_chunk_id():
    return str(uuid4())


@pytest.fixture
def sample_deck_id():
    return str(uuid4())


@pytest.fixture
def sample_slide_spec():
    """Valid slide specification."""
    return {
        "intent": "problem",
        "title": "The Problem with External Vector Databases",
        "bullets": [
            "Data duplication across systems increases complexity",
            "Network latency for every similarity search",
            "Additional infrastructure to manage and scale",
        ],
        "speaker_notes": "This slide covers the key challenges organizations face when using external vector databases. The main pain points are operational complexity and latency issues.",
        "citations": []
    }


@pytest.fixture
def sample_slide_spec_with_citations(sample_chunk_id):
    """Slide specification with citations."""
    return {
        "intent": "problem",
        "title": "The Problem with External Vector Databases",
        "bullets": [
            "Data duplication across systems increases complexity",
            "Network latency for every similarity search",
            "Additional infrastructure to manage and scale",
        ],
        "speaker_notes": "This slide covers the key challenges organizations face when using external vector databases. The main pain points are operational complexity.",
        "citations": [
            {"chunk_id": sample_chunk_id, "title": "RAG Overview", "url": None}
        ]
    }


# -----------------------------------------------------------------------------
# Model Tests
# -----------------------------------------------------------------------------


class TestModels:
    """Test Pydantic model validation."""
    
    def test_doc_type_enum(self):
        """Test doc_type enum values exist in DB-loaded enums."""
        assert "note" in config.VALID_ENUMS["doc_type"]
        assert "article" in config.VALID_ENUMS["doc_type"]
        assert "external" in config.VALID_ENUMS["doc_type"]
    
    def test_trust_level_enum(self):
        """Test trust_level enum values exist in DB-loaded enums."""
        assert "low" in config.VALID_ENUMS["trust_level"]
        assert "medium" in config.VALID_ENUMS["trust_level"]
        assert "high" in config.VALID_ENUMS["trust_level"]
    
    def test_slide_intent_enum(self):
        """Test slide_intent enum values exist in DB-loaded enums."""
        assert "problem" in config.VALID_ENUMS["slide_intent"]
        assert "why-postgres" in config.VALID_ENUMS["slide_intent"]
        assert "what-is-rag" in config.VALID_ENUMS["slide_intent"]
    
    def test_gate_decision_enum(self):
        """Test gate_decision enum values exist in DB-loaded enums."""
        assert "pass" in config.VALID_ENUMS["gate_decision"]
        assert "fail" in config.VALID_ENUMS["gate_decision"]


# -----------------------------------------------------------------------------
# Reranking Tests
# -----------------------------------------------------------------------------


class TestReranking:
    """Tests for cross-encoder reranking functionality."""
    
    def test_rerank_chunks_sorts_by_score(self):
        """Test rerank_chunks sorts results by cross-encoder score."""
        from src.mcp_server import rerank_chunks
        import src.mcp_server as mcp_server
        
        # Mock chunks with content
        chunks = [
            {"chunk_id": "1", "content": "Low relevance content", "combined_score": 0.9},
            {"chunk_id": "2", "content": "Medium relevance content", "combined_score": 0.8},
            {"chunk_id": "3", "content": "High relevance content", "combined_score": 0.7},
        ]
        
        # Mock the reranker to return predictable scores
        mock_reranker = MagicMock()
        mock_reranker.predict.return_value = [0.2, 0.5, 0.9]  # chunk 3 should be first
        
        with patch.object(mcp_server, 'get_reranker', return_value=mock_reranker):
            results = rerank_chunks("test query", chunks, top_k=3)
            
            # Verify sorted by rerank_score descending
            assert results[0]["chunk_id"] == "3"  # highest score
            assert results[0]["rerank_score"] == 0.9
            assert results[1]["chunk_id"] == "2"  # medium score
            assert results[1]["rerank_score"] == 0.5
            assert results[2]["chunk_id"] == "1"  # lowest score
            assert results[2]["rerank_score"] == 0.2
    
    def test_rerank_chunks_limits_to_top_k(self):
        """Test rerank_chunks returns only top_k results."""
        from src.mcp_server import rerank_chunks
        import src.mcp_server as mcp_server
        
        chunks = [
            {"chunk_id": str(i), "content": f"Content {i}", "combined_score": 0.5}
            for i in range(10)
        ]
        
        mock_reranker = MagicMock()
        # Give each chunk a different score
        mock_reranker.predict.return_value = [float(i) / 10 for i in range(10)]
        
        with patch.object(mcp_server, 'get_reranker', return_value=mock_reranker):
            results = rerank_chunks("test query", chunks, top_k=3)
            
            assert len(results) == 3
            # Should have the highest scores (0.9, 0.8, 0.7)
            assert results[0]["rerank_score"] == 0.9
            assert results[1]["rerank_score"] == 0.8
            assert results[2]["rerank_score"] == 0.7
    
    def test_rerank_chunks_empty_input(self):
        """Test rerank_chunks handles empty input gracefully."""
        from src.mcp_server import rerank_chunks
        
        results = rerank_chunks("test query", [], top_k=10)
        assert results == []
    
    def test_rerank_chunks_graceful_fallback_on_error(self):
        """Test rerank_chunks falls back to original results on error."""
        from src.mcp_server import rerank_chunks
        import src.mcp_server as mcp_server
        
        chunks = [
            {"chunk_id": "1", "content": "Content 1", "combined_score": 0.9},
            {"chunk_id": "2", "content": "Content 2", "combined_score": 0.8},
            {"chunk_id": "3", "content": "Content 3", "combined_score": 0.7},
        ]
        
        mock_reranker = MagicMock()
        mock_reranker.predict.side_effect = Exception("Model loading failed")
        
        with patch.object(mcp_server, 'get_reranker', return_value=mock_reranker):
            results = rerank_chunks("test query", chunks, top_k=2)
            
            # Should return first top_k of original chunks
            assert len(results) == 2
            assert results[0]["chunk_id"] == "1"
            assert results[1]["chunk_id"] == "2"
    
    @pytest.mark.asyncio
    async def test_search_chunks_with_reranking_enabled(self, mock_conn):
        """Test search_chunks uses reranking when RERANK_ENABLED=true."""
        from src.mcp_server import mcp_search_chunks
        import src.mcp_server as mcp_server
        
        # Mock database response with 50 chunks (RERANK_TOP_K default)
        mock_rows = []
        for i in range(50):
            mock_rows.append({
                "chunk_id": uuid4(),
                "doc_id": uuid4(),
                "content": f"Content about topic {i}",
                "doc_title": f"Doc {i}",
                "trust_level": "high",
                "semantic_score": 0.9 - (i * 0.01),
                "lexical_score": 0.8 - (i * 0.01),
                "combined_score": 0.85 - (i * 0.01),
                "semantic_rank": i + 1,
                "lexical_rank": i + 1,
            })
        mock_conn.fetch.return_value = mock_rows
        
        # Mock reranker
        mock_reranker = MagicMock()
        # Give varied scores to shuffle results
        mock_reranker.predict.return_value = [float(49 - i) / 50 for i in range(50)]
        
        # Save original values and enable reranking
        original_enabled = mcp_server.RERANK_ENABLED
        original_top_k = mcp_server.RERANK_TOP_K
        mcp_server.RERANK_ENABLED = True
        mcp_server.RERANK_TOP_K = 50
        
        try:
            with patch.object(mcp_server, 'get_connection') as mock_get_conn, \
                 patch.object(mcp_server, 'get_embedding', return_value=[0.1] * 1536), \
                 patch.object(mcp_server, 'get_reranker', return_value=mock_reranker):
                
                mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
                
                results = await mcp_search_chunks(query="test query", top_k=10)
                
                # Should return 10 results (reranked from 50 candidates)
                assert len(results) == 10
                
                # Results should have rerank_score
                assert "rerank_score" in results[0]
                
                # Verify fetch was called with 50 (RERANK_TOP_K)
                # conn.fetch args: SQL, embedding, query, filters, top_k, semantic_weight, lexical_weight
                call_args = mock_conn.fetch.call_args[0]  # positional args tuple
                assert call_args[4] == 50  # top_k is at index 4
        finally:
            mcp_server.RERANK_ENABLED = original_enabled
            mcp_server.RERANK_TOP_K = original_top_k
    
    @pytest.mark.asyncio
    async def test_search_chunks_with_reranking_disabled(self, mock_conn):
        """Test search_chunks bypasses reranking when RERANK_ENABLED=false."""
        from src.mcp_server import mcp_search_chunks
        import src.mcp_server as mcp_server
        
        mock_rows = [{
            "chunk_id": uuid4(),
            "doc_id": uuid4(),
            "content": "Test content",
            "doc_title": "Test Doc",
            "trust_level": "high",
            "semantic_score": 0.9,
            "lexical_score": 0.8,
            "combined_score": 0.85,
            "semantic_rank": 1,
            "lexical_rank": 1,
        }]
        mock_conn.fetch.return_value = mock_rows
        
        # Save original value and disable reranking
        original_enabled = mcp_server.RERANK_ENABLED
        mcp_server.RERANK_ENABLED = False
        
        try:
            with patch.object(mcp_server, 'get_connection') as mock_get_conn, \
                 patch.object(mcp_server, 'get_embedding', return_value=[0.1] * 1536):
                
                mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
                mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
                
                results = await mcp_search_chunks(query="test query", top_k=10)
                
                # Results should NOT have rerank_score
                assert "rerank_score" not in results[0]
                
                # Verify fetch was called with 10 (original top_k)
                # conn.fetch args: SQL, embedding, query, filters, top_k, semantic_weight, lexical_weight
                call_args = mock_conn.fetch.call_args[0]  # positional args tuple
                assert call_args[4] == 10  # top_k is at index 4
        finally:
            mcp_server.RERANK_ENABLED = original_enabled


# -----------------------------------------------------------------------------
# Search Chunks Tool Tests
# -----------------------------------------------------------------------------


class TestSearchChunks:
    """Tests for search_chunks tool."""
    
    @pytest.mark.asyncio
    async def test_search_chunks_basic(self, mock_conn, mock_openai):
        """Test basic search without filters."""
        from src.mcp_server import mcp_search_chunks
        import src.mcp_server as mcp_server
        
        # Mock database response
        mock_conn.fetch.return_value = [
            {
                "chunk_id": uuid4(),
                "doc_id": uuid4(),
                "content": "RAG combines retrieval with generation",
                "doc_title": "RAG Overview",
                "trust_level": "high",
                "semantic_score": 0.95,
                "lexical_score": 0.8,
                "combined_score": 0.9,
                "semantic_rank": 1,
                "lexical_rank": 2,
            }
        ]
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn, \
             patch.object(mcp_server, 'get_embedding', return_value=[0.1] * 1536):
            
            # Setup async context manager
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            results = await mcp_search_chunks(
                query="What is RAG?",
                top_k=10
            )
            
            assert len(results) == 1
            assert results[0]["content"] == "RAG combines retrieval with generation"
            assert results[0]["trust_level"] == "high"
    
    @pytest.mark.asyncio
    async def test_search_chunks_with_filters(self, mock_conn, mock_openai):
        """Test search with doc_type and trust_level filters."""
        from src.mcp_server import mcp_search_chunks
        import src.mcp_server as mcp_server
        
        mock_conn.fetch.return_value = []
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn, \
             patch.object(mcp_server, 'get_embedding', return_value=[0.1] * 1536):
            
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            results = await mcp_search_chunks(
                query="Postgres vectors",
                doc_type="external",
                trust_level="high",
                tags=["rag", "postgres"],
                top_k=5
            )
            
            assert isinstance(results, list)
            # Verify the fetch was called with filters in the query
            mock_conn.fetch.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_search_chunks_empty_results(self, mock_conn):
        """Test search returning no results."""
        from src.mcp_server import mcp_search_chunks
        import src.mcp_server as mcp_server
        
        mock_conn.fetch.return_value = []
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn, \
             patch.object(mcp_server, 'get_embedding', return_value=[0.1] * 1536):
            
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            results = await mcp_search_chunks(
                query="nonexistent topic xyz",
                top_k=10
            )
            
            assert results == []


# -----------------------------------------------------------------------------
# Get Chunk Tool Tests
# -----------------------------------------------------------------------------


class TestGetChunk:
    """Tests for get_chunk tool."""
    
    @pytest.mark.asyncio
    async def test_get_chunk_success(self, mock_conn, sample_chunk_id):
        """Test retrieving an existing chunk."""
        from src.mcp_server import mcp_get_chunk
        import src.mcp_server as mcp_server
        
        chunk_uuid = UUID(sample_chunk_id)
        doc_uuid = uuid4()
        
        mock_conn.fetchrow.return_value = {
            "chunk_id": chunk_uuid,
            "doc_id": doc_uuid,
            "content": "Test content about RAG",
            "content_hash": "abc123",
            "section_header": "Introduction",
            "token_count": 50,
            "doc_title": "RAG Guide",
            "doc_type": "external",
            "trust_level": "high",
            "tags": ["rag", "ai"],
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_get_chunk(sample_chunk_id)
            
            assert result["chunk_id"] == sample_chunk_id
            assert result["content"] == "Test content about RAG"
            assert result["doc_title"] == "RAG Guide"
            assert result["tags"] == ["rag", "ai"]
    
    @pytest.mark.asyncio
    async def test_get_chunk_not_found(self, mock_conn, sample_chunk_id):
        """Test retrieving a non-existent chunk raises error."""
        from src.mcp_server import mcp_get_chunk
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = None
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with pytest.raises(ValueError, match="Chunk not found"):
                await mcp_get_chunk(sample_chunk_id)


# -----------------------------------------------------------------------------
# Create Deck Tool Tests
# -----------------------------------------------------------------------------


class TestCreateDeck:
    """Tests for create_deck tool."""
    
    @pytest.mark.asyncio
    async def test_create_deck_basic(self, mock_conn):
        """Test creating a deck with minimal parameters."""
        from src.mcp_server import mcp_create_deck
        import src.mcp_server as mcp_server
        
        deck_id = uuid4()
        mock_conn.fetchval.return_value = deck_id
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_create_deck(
                topic="Postgres as AI Server",
                target_slides=15
            )
            
            assert result == str(deck_id)
            mock_conn.fetchval.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_deck_with_style(self, mock_conn):
        """Test creating a deck with style contract."""
        from src.mcp_server import mcp_create_deck
        import src.mcp_server as mcp_server
        
        deck_id = uuid4()
        mock_conn.fetchval.return_value = deck_id
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_create_deck(
                topic="AI in Databases",
                target_slides=10,
                description="A technical talk",
                tone="casual",
                audience="developers",
                bullet_style="concise"
            )
            
            assert result == str(deck_id)


# -----------------------------------------------------------------------------
# Get Deck State Tool Tests
# -----------------------------------------------------------------------------


class TestGetDeckState:
    """Tests for get_deck_state tool."""
    
    @pytest.mark.asyncio
    async def test_get_deck_state_success(self, mock_conn, sample_deck_id):
        """Test getting deck state for an existing deck."""
        from src.mcp_server import mcp_get_deck_state
        import src.mcp_server as mcp_server
        
        mock_conn.fetchval.return_value = json.dumps({
            "deck": {"deck_id": sample_deck_id, "topic": "Test", "target_slides": 14},
            "coverage": {"covered_intents": 5, "missing": ["problem", "thesis"]},
            "health": {"total_retries": 2, "completion_pct": 35.7},
            "slides": []
        })
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_get_deck_state(sample_deck_id)
            
            assert "deck" in result
            assert "coverage" in result
            assert "health" in result
    
    @pytest.mark.asyncio
    async def test_get_deck_state_not_found(self, mock_conn, sample_deck_id):
        """Test getting state for non-existent deck raises error."""
        from src.mcp_server import mcp_get_deck_state
        import src.mcp_server as mcp_server
        
        mock_conn.fetchval.return_value = None
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with pytest.raises(ValueError, match="Deck not found"):
                await mcp_get_deck_state(sample_deck_id)


# -----------------------------------------------------------------------------
# Pick Next Intent Tool Tests
# -----------------------------------------------------------------------------


class TestPickNextIntent:
    """Tests for pick_next_intent tool."""
    
    @pytest.mark.asyncio
    async def test_pick_next_intent_returns_intent(self, mock_conn, sample_deck_id):
        """Test picking next intent when intents are missing."""
        from src.mcp_server import mcp_pick_next_intent
        import src.mcp_server as mcp_server
        
        mock_conn.fetchval.return_value = "problem"
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_pick_next_intent(sample_deck_id)
            
            assert result == "problem"
    
    @pytest.mark.asyncio
    async def test_pick_next_intent_all_covered(self, mock_conn, sample_deck_id):
        """Test picking next intent when all are covered."""
        from src.mcp_server import mcp_pick_next_intent
        import src.mcp_server as mcp_server
        
        mock_conn.fetchval.return_value = None
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_pick_next_intent(sample_deck_id)
            
            assert result is None


# -----------------------------------------------------------------------------
# Validate Slide Structure Tool Tests
# -----------------------------------------------------------------------------


class TestValidateSlideStructure:
    """Tests for validate_slide_structure tool."""
    
    @pytest.mark.asyncio
    async def test_validate_slide_structure_valid(self, mock_conn, sample_slide_spec):
        """Test validating a valid slide spec."""
        from src.mcp_server import mcp_validate_slide_structure
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = {
            "is_valid": True,
            "errors": "[]"
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_validate_slide_structure(sample_slide_spec)
            
            assert result["is_valid"] is True
            assert result["errors"] == []
    
    @pytest.mark.asyncio
    async def test_validate_slide_structure_invalid(self, mock_conn):
        """Test validating an invalid slide spec."""
        from src.mcp_server import mcp_validate_slide_structure
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = {
            "is_valid": False,
            "errors": json.dumps(["Missing or empty title", "Too few bullets: 1 (min: 3)"])
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            invalid_spec = {
                "intent": "problem",
                "title": "",
                "bullets": ["Only one bullet"],
                "speaker_notes": ""
            }
            
            result = await mcp_validate_slide_structure(invalid_spec)
            
            assert result["is_valid"] is False
            assert len(result["errors"]) == 2


# -----------------------------------------------------------------------------
# Validate Citations Tool Tests
# -----------------------------------------------------------------------------


class TestValidateCitations:
    """Tests for validate_citations tool."""
    
    @pytest.mark.asyncio
    async def test_validate_citations_valid(self, mock_conn, sample_slide_spec_with_citations):
        """Test validating valid citations."""
        from src.mcp_server import mcp_validate_citations
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = {
            "is_valid": True,
            "citation_count": 1,
            "errors": "[]"
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_validate_citations(sample_slide_spec_with_citations)
            
            assert result["is_valid"] is True
            assert result["citation_count"] == 1
    
    @pytest.mark.asyncio
    async def test_validate_citations_missing(self, mock_conn, sample_slide_spec):
        """Test validating missing citations."""
        from src.mcp_server import mcp_validate_citations
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = {
            "is_valid": False,
            "citation_count": 0,
            "errors": json.dumps(["Too few citations: 0 (min: 1)"])
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_validate_citations(sample_slide_spec)
            
            assert result["is_valid"] is False
            assert result["citation_count"] == 0


# -----------------------------------------------------------------------------
# Check Retrieval Quality Tool Tests (G1)
# -----------------------------------------------------------------------------


class TestCheckRetrievalQuality:
    """Tests for mcp_check_retrieval_quality tool."""

    @pytest.mark.asyncio
    async def test_valid_retrieval_passes(self, mock_conn):
        """Good retrieval results pass the G1 gate."""
        from src.mcp_server import mcp_check_retrieval_quality
        import src.mcp_server as mcp_server

        mock_conn.fetchrow.return_value = {
            "is_valid": True,
            "chunk_count": 5,
            "top_score": 0.75,
            "errors": "[]",
        }

        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await mcp_check_retrieval_quality(
                search_results=[
                    {"chunk_id": "a", "combined_score": 0.75},
                    {"chunk_id": "b", "combined_score": 0.6},
                    {"chunk_id": "c", "combined_score": 0.5},
                    {"chunk_id": "d", "combined_score": 0.4},
                    {"chunk_id": "e", "combined_score": 0.3},
                ],
            )

            assert result["is_valid"] is True
            assert result["chunk_count"] == 5
            assert result["top_score"] == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_insufficient_retrieval_fails(self, mock_conn):
        """Too few chunks with low scores fails the G1 gate."""
        from src.mcp_server import mcp_check_retrieval_quality
        import src.mcp_server as mcp_server

        mock_conn.fetchrow.return_value = {
            "is_valid": False,
            "chunk_count": 1,
            "top_score": 0.2,
            "errors": json.dumps(["Too few chunks: 1 (min: 3)", "Top score too low: 0.200 (min: 0.300)"]),
        }

        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await mcp_check_retrieval_quality(
                search_results=[{"chunk_id": "a", "combined_score": 0.2}],
            )

            assert result["is_valid"] is False
            assert len(result["errors"]) == 2


# -----------------------------------------------------------------------------
# Check Novelty Tool Tests
# -----------------------------------------------------------------------------


class TestCheckNovelty:
    """Tests for check_novelty tool."""
    
    @pytest.mark.asyncio
    async def test_check_novelty_is_novel(self, mock_conn, sample_deck_id):
        """Test checking novelty for novel content."""
        from src.mcp_server import mcp_check_novelty
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = {
            "is_novel": True,
            "max_similarity": 0.45,
            "most_similar_slide_no": 3,
            "most_similar_intent": "comparison"
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn, \
             patch.object(mcp_server, 'get_embedding', return_value=[0.1] * 1536):
            
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_check_novelty(
                deck_id=sample_deck_id,
                candidate_text="Completely new content about something different"
            )
            
            assert result["is_novel"] is True
            assert result["max_similarity"] < 0.85
    
    @pytest.mark.asyncio
    async def test_check_novelty_is_duplicate(self, mock_conn, sample_deck_id):
        """Test checking novelty for duplicate content."""
        from src.mcp_server import mcp_check_novelty
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = {
            "is_novel": False,
            "max_similarity": 0.92,
            "most_similar_slide_no": 5,
            "most_similar_intent": "problem"
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn, \
             patch.object(mcp_server, 'get_embedding', return_value=[0.1] * 1536):
            
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_check_novelty(
                deck_id=sample_deck_id,
                candidate_text="Very similar content to existing slide"
            )
            
            assert result["is_novel"] is False
            assert result["max_similarity"] > 0.85
            assert result["most_similar_slide_no"] == 5


# -----------------------------------------------------------------------------
# Check Grounding Tool Tests
# -----------------------------------------------------------------------------


class TestCheckGrounding:
    """Tests for check_grounding tool."""
    
    @pytest.mark.asyncio
    async def test_check_grounding_all_grounded(self, mock_conn, sample_slide_spec_with_citations):
        """Test grounding check when all bullets are grounded."""
        from src.mcp_server import mcp_check_grounding
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = {
            "is_grounded": True,
            "ungrounded_bullets": [],
            "min_similarity": 0.82,
            "grounding_details": json.dumps([
                {"bullet_index": 1, "max_similarity": 0.85, "grounded": True},
                {"bullet_index": 2, "max_similarity": 0.82, "grounded": True},
                {"bullet_index": 3, "max_similarity": 0.88, "grounded": True},
            ])
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn, \
             patch.object(mcp_server, 'get_embedding', return_value=[0.1] * 1536):
            
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_check_grounding(sample_slide_spec_with_citations)
            
            assert result["is_grounded"] is True
            assert result["ungrounded_bullets"] == []
    
    @pytest.mark.asyncio
    async def test_check_grounding_some_ungrounded(self, mock_conn, sample_slide_spec_with_citations):
        """Test grounding check when some bullets are ungrounded."""
        from src.mcp_server import mcp_check_grounding
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = {
            "is_grounded": False,
            "ungrounded_bullets": [2],
            "min_similarity": 0.55,
            "grounding_details": json.dumps([
                {"bullet_index": 1, "max_similarity": 0.85, "grounded": True},
                {"bullet_index": 2, "max_similarity": 0.55, "grounded": False},
                {"bullet_index": 3, "max_similarity": 0.78, "grounded": True},
            ])
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn, \
             patch.object(mcp_server, 'get_embedding', return_value=[0.1] * 1536):
            
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_check_grounding(sample_slide_spec_with_citations)
            
            assert result["is_grounded"] is False
            assert 2 in result["ungrounded_bullets"]
    
    @pytest.mark.asyncio
    async def test_check_grounding_no_bullets(self, mock_conn):
        """Test grounding check with no bullets."""
        from src.mcp_server import mcp_check_grounding
        
        slide_spec = {"intent": "problem", "title": "Test", "bullets": [], "citations": []}
        
        result = await mcp_check_grounding(slide_spec)
        
        assert result["is_grounded"] is False


# -----------------------------------------------------------------------------
# Commit Slide Tool Tests
# -----------------------------------------------------------------------------


class TestCommitSlide:
    """Tests for commit_slide tool."""
    
    @pytest.mark.asyncio
    async def test_commit_slide_success(self, mock_conn, sample_deck_id, sample_slide_spec_with_citations):
        """Test successfully committing a slide."""
        from src.mcp_server import mcp_commit_slide
        import src.mcp_server as mcp_server
        
        slide_id = uuid4()
        mock_conn.fetchrow.return_value = {
            "success": True,
            "slide_id": slide_id,
            "errors": "[]"
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_commit_slide(
                deck_id=sample_deck_id,
                slide_no=1,
                slide_spec=sample_slide_spec_with_citations,
                novelty_passed=True,
                novelty_score=0.3,
                grounding_passed=True,
                grounding_score=0.85
            )
            
            assert result["success"] is True
            assert result["slide_id"] == str(slide_id)
            assert result["errors"] == []
    
    @pytest.mark.asyncio
    async def test_commit_slide_validation_failure(self, mock_conn, sample_deck_id, sample_slide_spec):
        """Test commit failure due to validation errors."""
        from src.mcp_server import mcp_commit_slide
        import src.mcp_server as mcp_server
        
        mock_conn.fetchrow.return_value = {
            "success": False,
            "slide_id": None,
            "errors": json.dumps(["Too few citations: 0 (min: 1)"])
        }
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_commit_slide(
                deck_id=sample_deck_id,
                slide_no=1,
                slide_spec=sample_slide_spec
            )
            
            assert result["success"] is False
            assert result["slide_id"] is None
            assert len(result["errors"]) > 0


# -----------------------------------------------------------------------------
# Get Run Report Tool Tests
# -----------------------------------------------------------------------------


class TestGetRunReport:
    """Tests for get_run_report tool."""
    
    @pytest.mark.asyncio
    async def test_get_run_report_success(self, mock_conn, sample_deck_id):
        """Test getting a run report."""
        from src.mcp_server import mcp_get_run_report
        import src.mcp_server as mcp_server
        
        mock_conn.fetchval.return_value = json.dumps({
            "deck_id": sample_deck_id,
            "generated_at": "2026-02-03T12:00:00Z",
            "summary": {
                "topic": "Test Topic",
                "target_slides": 14,
                "actual_slides": 10,
                "completion_pct": 71.4
            },
            "coverage": {
                "covered_intents": 10,
                "covered": ["problem", "thesis"],
                "missing": ["thanks"]
            },
            "gate_summary": {
                "g2_citation": {"total": 10, "passed": 10, "failed": 0},
                "g3_format": {"total": 10, "passed": 9, "failed": 1}
            },
            "top_failure_reasons": [],
            "slides": []
        })
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await mcp_get_run_report(sample_deck_id)
            
            assert result["deck_id"] == sample_deck_id
            assert "summary" in result
            assert "coverage" in result
            assert "gate_summary" in result
    
    @pytest.mark.asyncio
    async def test_get_run_report_not_found(self, mock_conn, sample_deck_id):
        """Test getting report for non-existent deck."""
        from src.mcp_server import mcp_get_run_report
        import src.mcp_server as mcp_server
        
        mock_conn.fetchval.return_value = None
        
        with patch.object(mcp_server, 'get_connection') as mock_get_conn:
            mock_get_conn.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_get_conn.return_value.__aexit__ = AsyncMock(return_value=None)
            
            with pytest.raises(ValueError, match="Deck not found"):
                await mcp_get_run_report(sample_deck_id)


# -----------------------------------------------------------------------------
# Database Module Tests
# -----------------------------------------------------------------------------


class TestDatabaseModule:
    """Tests for src/db.py module."""
    
    @pytest.mark.asyncio
    async def test_get_pool_missing_url(self):
        """Test get_pool raises error when DATABASE_URL is not set."""
        from src import db
        
        # Save original and clear
        original_url = db.DATABASE_URL
        db.DATABASE_URL = None
        db._pool = None
        
        try:
            with pytest.raises(ValueError, match="DATABASE_URL"):
                await db.get_pool()
        finally:
            # Restore
            db.DATABASE_URL = original_url
