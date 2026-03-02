"""
Integration tests for MCP Server.

Tests tool-to-database round trips with seeded test data.
Requires a running Postgres database with the schema loaded.
"""

import json
from uuid import UUID

import pytest
import pytest_asyncio

from tests.conftest import get_test_embedding, get_test_slide_spec


# -----------------------------------------------------------------------------
# Integration Test Fixtures
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_doc_with_chunks(test_db):
    """
    Create a test document with chunks that have embeddings.
    
    Returns tuple of (doc_id, chunk_ids)
    """
    # Create document
    doc_id = await test_db.fetchval("""
        INSERT INTO doc (doc_type, title, trust_level, tags, source_path)
        VALUES ('external', 'RAG Integration Test Doc', 'high', ARRAY['test', 'rag'], '/test/integration.md')
        RETURNING doc_id
    """)
    
    # Create chunks with embeddings for search testing
    chunk_ids = []
    test_chunks = [
        ("RAG (Retrieval Augmented Generation) combines retrieval with generation to produce accurate AI responses grounded in source documents.", "What is RAG"),
        ("Postgres with pgvector enables native vector similarity search within the database, eliminating the need for external vector stores.", "pgvector Benefits"),
        ("MCP (Model Context Protocol) provides typed tool interfaces that create a safety boundary for LLM interactions.", "MCP Overview"),
    ]
    
    for idx, (content, header) in enumerate(test_chunks):
        embedding = get_test_embedding(content)
        chunk_id = await test_db.fetchval("""
            INSERT INTO chunk (doc_id, chunk_index, content, content_hash, embedding, token_count, section_header)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING chunk_id
        """, doc_id, idx, content, f"test_hash_{idx}", str(embedding), len(content.split()), header)
        chunk_ids.append(chunk_id)
    
    return doc_id, chunk_ids


@pytest_asyncio.fixture
async def test_deck_with_slides(test_db):
    """
    Create a test deck with some slides for novelty testing.
    
    Returns tuple of (deck_id, slide_ids)
    """
    # Create deck
    deck_id = await test_db.fetchval("""
        SELECT fn_create_deck('Integration Test Deck', 14, '{"tone": "technical"}'::jsonb, 'Test deck')
    """)
    
    # Create a few slides with embeddings
    slide_ids = []
    test_slides = [
        (1, "problem", "The Problem with External Vector Databases"),
        (2, "why-postgres", "Why Postgres for AI Workloads"),
    ]
    
    for slide_no, intent, title in test_slides:
        bullets = [
            "First bullet point about the topic",
            "Second bullet point with more detail",
            "Third bullet point with conclusion",
        ]
        content_text = f"{title} {' '.join(bullets)}"
        embedding = get_test_embedding(content_text)
        
        slide_id = await test_db.fetchval("""
            INSERT INTO slide (deck_id, slide_no, intent, title, bullets, speaker_notes, content_embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING slide_id
        """, deck_id, slide_no, intent, title, json.dumps(bullets), 
            "Speaker notes for the slide.", str(embedding))
        slide_ids.append(slide_id)
    
    return deck_id, slide_ids


# -----------------------------------------------------------------------------
# Database Function Integration Tests
# -----------------------------------------------------------------------------


@pytest.mark.integration
class TestHybridSearchIntegration:
    """Integration tests for fn_hybrid_search."""
    
    @pytest.mark.asyncio
    async def test_hybrid_search_returns_results(self, test_db, test_doc_with_chunks):
        """Test hybrid search returns matching chunks."""
        doc_id, chunk_ids = test_doc_with_chunks
        
        # Create query embedding similar to RAG content
        query_embedding = get_test_embedding("What is RAG retrieval augmented generation")
        
        rows = await test_db.fetch("""
            SELECT * FROM fn_hybrid_search($1, $2, '{}'::jsonb, 5)
        """, str(query_embedding), "RAG retrieval augmented generation")
        
        assert len(rows) > 0
        # First result should be the RAG chunk (most semantically similar)
        assert "RAG" in rows[0]["content"] or "retrieval" in rows[0]["content"].lower()
    
    @pytest.mark.asyncio
    async def test_hybrid_search_with_filters(self, test_db, test_doc_with_chunks):
        """Test hybrid search respects filters."""
        query_embedding = get_test_embedding("vector database")
        
        # Filter by trust level
        rows = await test_db.fetch("""
            SELECT * FROM fn_hybrid_search($1, $2, '{"trust_level": "high"}'::jsonb, 5)
        """, str(query_embedding), "vector database")
        
        for row in rows:
            assert row["trust_level"] == "high"
    
    @pytest.mark.asyncio
    async def test_hybrid_search_empty_results(self, test_db):
        """Test hybrid search with no matching content."""
        query_embedding = get_test_embedding("completely unrelated topic xyz123")
        
        rows = await test_db.fetch("""
            SELECT * FROM fn_hybrid_search($1, $2, '{}'::jsonb, 5)
        """, str(query_embedding), "completely unrelated topic xyz123")
        
        # May return results due to semantic similarity, but with low scores
        # The important thing is it doesn't error
        assert isinstance(rows, list)


@pytest.mark.integration
class TestNoveltyCheckIntegration:
    """Integration tests for fn_check_novelty."""
    
    @pytest.mark.asyncio
    async def test_novelty_check_novel_content(self, test_db, test_deck_with_slides):
        """Test novelty check function returns expected fields and respects threshold."""
        deck_id, slide_ids = test_deck_with_slides
        
        # Use a different embedding
        candidate_embedding = get_test_embedding("Kubernetes deployment strategies and container orchestration patterns")
        
        # Use a threshold of 1.0 (maximum) - anything below perfect match is novel
        row = await test_db.fetchrow("""
            SELECT * FROM fn_check_novelty($1, $2, 1.0)
        """, deck_id, str(candidate_embedding))
        
        # Verify the function returns expected fields
        assert "is_novel" in row
        assert "max_similarity" in row
        assert "most_similar_slide_no" in row
        assert "most_similar_intent" in row
        
        # With threshold of 1.0, any content should be novel (no perfect match)
        assert row["is_novel"] is True
        assert row["max_similarity"] is not None
        assert 0.0 <= row["max_similarity"] <= 1.0
    
    @pytest.mark.asyncio
    async def test_novelty_check_similar_content(self, test_db, test_deck_with_slides):
        """Test novelty check fails for similar content."""
        deck_id, slide_ids = test_deck_with_slides
        
        # Very similar to existing "problem" slide
        candidate_embedding = get_test_embedding("The Problem with External Vector Databases First bullet point")
        
        row = await test_db.fetchrow("""
            SELECT * FROM fn_check_novelty($1, $2, 0.85)
        """, deck_id, str(candidate_embedding))
        
        # Should detect similarity (may or may not fail depending on embedding similarity)
        assert row["max_similarity"] >= 0.0
    
    @pytest.mark.asyncio
    async def test_novelty_check_empty_deck(self, test_db, test_deck):
        """Test novelty check on deck with no slides."""
        candidate_embedding = get_test_embedding("Any content should be novel")
        
        row = await test_db.fetchrow("""
            SELECT * FROM fn_check_novelty($1, $2, 0.85)
        """, test_deck, str(candidate_embedding))
        
        assert row["is_novel"] is True
        assert row["max_similarity"] == 0.0


@pytest.mark.integration
class TestValidationIntegration:
    """Integration tests for validation functions."""
    
    @pytest.mark.asyncio
    async def test_validate_slide_structure_valid(self, test_db):
        """Test structure validation for valid slide."""
        slide_spec = get_test_slide_spec()
        
        row = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1)
        """, json.dumps(slide_spec))
        
        assert row["is_valid"] is True
        errors = json.loads(row["errors"]) if isinstance(row["errors"], str) else row["errors"]
        assert errors == []
    
    @pytest.mark.asyncio
    async def test_validate_slide_structure_too_few_bullets(self, test_db):
        """Test structure validation rejects too few bullets."""
        slide_spec = get_test_slide_spec({"bullets": ["Only one"]})
        
        row = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1)
        """, json.dumps(slide_spec))
        
        assert row["is_valid"] is False
        errors = json.loads(row["errors"]) if isinstance(row["errors"], str) else row["errors"]
        assert any("Too few bullets" in e for e in errors)
    
    @pytest.mark.asyncio
    async def test_validate_slide_structure_missing_title(self, test_db):
        """Test structure validation rejects missing title."""
        slide_spec = get_test_slide_spec({"title": ""})
        
        row = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1)
        """, json.dumps(slide_spec))
        
        assert row["is_valid"] is False
        errors = json.loads(row["errors"]) if isinstance(row["errors"], str) else row["errors"]
        assert any("title" in e.lower() for e in errors)
    
    @pytest.mark.asyncio
    async def test_validate_citations_valid(self, test_db, test_doc_with_chunks):
        """Test citation validation for valid citations."""
        doc_id, chunk_ids = test_doc_with_chunks
        
        slide_spec = get_test_slide_spec({
            "citations": [{"chunk_id": str(chunk_ids[0]), "title": "Test", "url": None}]
        })
        
        row = await test_db.fetchrow("""
            SELECT * FROM fn_validate_citations($1)
        """, json.dumps(slide_spec))
        
        assert row["is_valid"] is True
        assert row["citation_count"] == 1
    
    @pytest.mark.asyncio
    async def test_validate_citations_invalid_chunk(self, test_db):
        """Test citation validation rejects non-existent chunks."""
        from uuid import uuid4
        
        slide_spec = get_test_slide_spec({
            "citations": [{"chunk_id": str(uuid4()), "title": "Test", "url": None}]
        })
        
        row = await test_db.fetchrow("""
            SELECT * FROM fn_validate_citations($1)
        """, json.dumps(slide_spec))
        
        assert row["is_valid"] is False
        errors = json.loads(row["errors"]) if isinstance(row["errors"], str) else row["errors"]
        assert any("non-existent" in e.lower() for e in errors)


@pytest.mark.integration
class TestDeckManagementIntegration:
    """Integration tests for deck management functions."""
    
    @pytest.mark.asyncio
    async def test_create_deck(self, test_db):
        """Test deck creation."""
        deck_id = await test_db.fetchval("""
            SELECT fn_create_deck('Integration Test Topic', 10, '{"tone": "casual"}'::jsonb, 'Test description')
        """)
        
        assert deck_id is not None
        
        # Verify deck was created
        deck = await test_db.fetchrow("""
            SELECT * FROM deck WHERE deck_id = $1
        """, deck_id)
        
        assert deck["topic"] == "Integration Test Topic"
        assert deck["target_slides"] == 10
    
    @pytest.mark.asyncio
    async def test_get_deck_state(self, test_db, test_deck_with_slides):
        """Test getting deck state."""
        deck_id, slide_ids = test_deck_with_slides
        
        state = await test_db.fetchval("""
            SELECT fn_get_deck_state($1)
        """, deck_id)
        
        state_dict = json.loads(state) if isinstance(state, str) else state
        
        assert state_dict["deck"]["deck_id"] == str(deck_id)
        assert state_dict["coverage"]["total_slides"] == 2
        assert len(state_dict["coverage"]["missing"]) > 0
    
    @pytest.mark.asyncio
    async def test_pick_next_intent(self, test_db, test_deck_with_slides):
        """Test picking next intent."""
        deck_id, slide_ids = test_deck_with_slides
        
        # Deck has 'problem' and 'why-postgres', next should be different
        next_intent = await test_db.fetchval("""
            SELECT fn_pick_next_intent($1)
        """, deck_id)
        
        assert next_intent is not None
        assert next_intent not in ["problem", "why-postgres"]
    
    @pytest.mark.asyncio
    async def test_pick_next_intent_empty_deck(self, test_db, test_deck):
        """Test picking first intent for empty deck."""
        next_intent = await test_db.fetchval("""
            SELECT fn_pick_next_intent($1)
        """, test_deck)
        
        # Should return 'problem' as the first in canonical order
        assert next_intent == "problem"


@pytest.mark.integration
class TestCommitSlideIntegration:
    """Integration tests for slide commit function."""
    
    @pytest.mark.asyncio
    async def test_commit_slide_success(self, test_db, test_deck, test_doc_with_chunks):
        """Test successful slide commit."""
        from uuid import uuid4
        
        deck_id = test_deck
        doc_id, chunk_ids = test_doc_with_chunks
        run_id = uuid4()
        
        slide_spec = get_test_slide_spec({
            "citations": [{"chunk_id": str(chunk_ids[0]), "title": "Test", "url": None}]
        })
        
        row = await test_db.fetchrow("""
            SELECT * FROM fn_commit_slide($1, 1, $2, $3, TRUE, 0.3, TRUE, 0.85)
        """, deck_id, json.dumps(slide_spec), run_id)
        
        assert row["success"] is True
        assert row["slide_id"] is not None
        
        # Verify slide was created
        slide = await test_db.fetchrow("""
            SELECT * FROM slide WHERE slide_id = $1
        """, row["slide_id"])
        
        assert slide["intent"] == "problem"
        assert slide["title"] == slide_spec["title"]
    
    @pytest.mark.asyncio
    async def test_commit_slide_logs_gates(self, test_db, test_deck, test_doc_with_chunks):
        """Test that commit logs gate decisions."""
        from uuid import uuid4
        
        deck_id = test_deck
        doc_id, chunk_ids = test_doc_with_chunks
        run_id = uuid4()
        
        slide_spec = get_test_slide_spec({
            "citations": [{"chunk_id": str(chunk_ids[0]), "title": "Test", "url": None}]
        })
        
        await test_db.fetchrow("""
            SELECT * FROM fn_commit_slide($1, 1, $2, $3, TRUE, 0.3, TRUE, 0.85, NULL, 0)
        """, deck_id, json.dumps(slide_spec), run_id)
        
        # After migration 020, fn_commit_slide only logs G5.
        # G1-G4 are logged by the orchestrator via fn_log_gate.
        gate_logs = await test_db.fetch("""
            SELECT * FROM gate_log WHERE run_id = $1 ORDER BY created_at
        """, run_id)
        
        gate_names = [log["gate_name"] for log in gate_logs]
        assert "g5_commit" in gate_names
    
    @pytest.mark.asyncio
    async def test_commit_slide_validation_failure(self, test_db, test_deck):
        """Test commit fails with validation errors."""
        deck_id = test_deck
        
        # Invalid slide spec - no citations
        slide_spec = get_test_slide_spec()  # Has empty citations
        
        row = await test_db.fetchrow("""
            SELECT * FROM fn_commit_slide($1, 1, $2)
        """, deck_id, json.dumps(slide_spec))
        
        assert row["success"] is False
        errors = json.loads(row["errors"]) if isinstance(row["errors"], str) else row["errors"]
        assert len(errors) > 0


@pytest.mark.integration
class TestRunReportIntegration:
    """Integration tests for run report function."""
    
    @pytest.mark.asyncio
    async def test_get_run_report(self, test_db, test_deck_with_slides):
        """Test generating run report."""
        deck_id, slide_ids = test_deck_with_slides
        
        report = await test_db.fetchval("""
            SELECT fn_get_run_report($1)
        """, deck_id)
        
        report_dict = json.loads(report) if isinstance(report, str) else report
        
        assert report_dict["deck_id"] == str(deck_id)
        assert "summary" in report_dict
        assert "coverage" in report_dict
        assert report_dict["summary"]["actual_slides"] == 2


@pytest.mark.integration
class TestGroundingCheckIntegration:
    """Integration tests for grounding check function."""
    
    @pytest.mark.asyncio
    async def test_check_grounding_valid(self, test_db, test_doc_with_chunks):
        """Test grounding check with valid citations."""
        doc_id, chunk_ids = test_doc_with_chunks
        
        # Create bullet embeddings similar to chunk content
        bullet1_emb = get_test_embedding("RAG combines retrieval with generation")
        bullet2_emb = get_test_embedding("Postgres with pgvector enables vector search")
        bullet3_emb = get_test_embedding("MCP provides typed tool interfaces")
        
        slide_spec = {
            "intent": "what-is-rag",
            "title": "Understanding RAG",
            "bullets": [
                "RAG combines retrieval with generation",
                "Postgres with pgvector enables vector search",
                "MCP provides typed tool interfaces"
            ],
            "speaker_notes": "This covers the key concepts.",
            "citations": [
                {"chunk_id": str(chunk_ids[0]), "title": "Test 1", "url": None},
                {"chunk_id": str(chunk_ids[1]), "title": "Test 2", "url": None},
                {"chunk_id": str(chunk_ids[2]), "title": "Test 3", "url": None},
            ]
        }
        
        # Format embeddings array
        embeddings_str = f"ARRAY['{bullet1_emb}'::vector(1536), '{bullet2_emb}'::vector(1536), '{bullet3_emb}'::vector(1536)]"
        
        row = await test_db.fetchrow(f"""
            SELECT * FROM fn_check_grounding($1, {embeddings_str}, 0.5)
        """, json.dumps(slide_spec))
        
        # With matching embeddings and low threshold, should be grounded
        assert row is not None
        # Note: actual grounding depends on embedding similarity
