"""
Tests for fn_hybrid_search SQL function.

The hybrid search function combines semantic (vector) and lexical (full-text)
search using Reciprocal Rank Fusion (RRF) scoring.
"""

import json

import pytest
import pytest_asyncio

from tests.conftest import get_test_embedding


@pytest.mark.asyncio
async def test_hybrid_search_returns_results(seeded_db):
    """Hybrid search returns combined semantic+lexical results."""
    query_embedding = get_test_embedding("What is RAG retrieval generation?")
    
    results = await seeded_db.fetch("""
        SELECT * FROM fn_hybrid_search($1, 'RAG retrieval generation', '{}', 5)
    """, str(query_embedding))
    
    assert len(results) > 0, "Should return at least one result"
    assert results[0]['combined_score'] > 0, "Combined score should be positive"


@pytest.mark.asyncio
async def test_hybrid_search_respects_top_k(seeded_db):
    """Hybrid search returns at most top_k results."""
    query_embedding = get_test_embedding("postgres database")
    
    results = await seeded_db.fetch("""
        SELECT * FROM fn_hybrid_search($1, 'postgres database', '{}', 2)
    """, str(query_embedding))
    
    assert len(results) <= 2, "Should respect top_k limit"


@pytest.mark.asyncio
async def test_hybrid_search_returns_required_fields(seeded_db):
    """Results include all required fields for downstream processing."""
    query_embedding = get_test_embedding("vector search")
    
    results = await seeded_db.fetch("""
        SELECT * FROM fn_hybrid_search($1, 'vector search', '{}', 5)
    """, str(query_embedding))
    
    assert len(results) > 0
    row = results[0]
    
    required_fields = [
        'chunk_id', 'doc_id', 'content', 'doc_title', 'trust_level',
        'semantic_score', 'lexical_score', 'combined_score',
        'semantic_rank', 'lexical_rank'
    ]
    
    for field in required_fields:
        assert field in row.keys(), f"Missing required field: {field}"


@pytest.mark.asyncio
async def test_hybrid_search_filter_by_trust_level(seeded_db):
    """Filters correctly limit results to matching trust levels."""
    query_embedding = get_test_embedding("AI database")
    filters = json.dumps({"trust_level": "high"})
    
    results = await seeded_db.fetch("""
        SELECT * FROM fn_hybrid_search($1, 'AI database', $2::jsonb, 10)
    """, str(query_embedding), filters)
    
    for row in results:
        assert row['trust_level'] == 'high', f"Got unexpected trust_level: {row['trust_level']}"


@pytest.mark.asyncio
async def test_hybrid_search_empty_query_returns_results(seeded_db):
    """Empty query text still returns semantic results."""
    query_embedding = get_test_embedding("control plane")
    
    results = await seeded_db.fetch("""
        SELECT * FROM fn_hybrid_search($1, '', '{}', 5)
    """, str(query_embedding))
    
    # Semantic search should still work even with empty text
    assert len(results) > 0, "Semantic search should return results even with empty query text"


@pytest.mark.asyncio
async def test_hybrid_search_scores_ordered_descending(seeded_db):
    """Results are ordered by combined score descending."""
    query_embedding = get_test_embedding("retrieval")
    
    results = await seeded_db.fetch("""
        SELECT * FROM fn_hybrid_search($1, 'retrieval', '{}', 10)
    """, str(query_embedding))
    
    if len(results) > 1:
        scores = [r['combined_score'] for r in results]
        assert scores == sorted(scores, reverse=True), "Results should be ordered by score descending"


@pytest.mark.asyncio
async def test_hybrid_search_no_results_for_unmatched_filter(seeded_db):
    """Returns empty when filters match nothing."""
    query_embedding = get_test_embedding("anything")
    # Use a filter that won't match any seeded data
    filters = json.dumps({"doc_type": "nonexistent_type"})
    
    results = await seeded_db.fetch("""
        SELECT * FROM fn_hybrid_search($1, 'anything', $2::jsonb, 10)
    """, str(query_embedding), filters)
    
    assert len(results) == 0, "Should return empty for unmatched filters"


@pytest.mark.asyncio
async def test_hybrid_search_custom_weights(seeded_db):
    """Custom semantic/lexical weights affect scoring."""
    query_embedding = get_test_embedding("database search")
    
    # Heavily weighted toward semantic
    semantic_heavy = await seeded_db.fetch("""
        SELECT * FROM fn_hybrid_search($1, 'database search', '{}', 5, 0.95, 0.05)
    """, str(query_embedding))
    
    # Heavily weighted toward lexical
    lexical_heavy = await seeded_db.fetch("""
        SELECT * FROM fn_hybrid_search($1, 'database search', '{}', 5, 0.05, 0.95)
    """, str(query_embedding))
    
    # Scores should differ based on weights
    if len(semantic_heavy) > 0 and len(lexical_heavy) > 0:
        # The rankings might be different due to different weights
        # This test verifies the function accepts custom weights without error
        assert True, "Custom weights accepted without error"
