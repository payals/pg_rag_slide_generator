"""
Tests for fn_check_retrieval_quality (G1 gate).

Covers:
- Passing with enough high-quality chunks
- Failing on too few chunks
- Failing on low top score
- Edge cases: null input, empty array, missing combined_score
"""

import json

import pytest


class TestCheckRetrievalQuality:
    """Tests for fn_check_retrieval_quality."""

    def _make_results(self, scores: list[float]) -> str:
        """Build a JSONB search-results array from a list of combined_scores."""
        return json.dumps([
            {"chunk_id": f"00000000-0000-0000-0000-{i:012d}", "combined_score": s}
            for i, s in enumerate(scores)
        ])

    @pytest.mark.asyncio
    async def test_good_results_pass(self, test_db):
        """3+ chunks with top score > 0.3 passes."""
        results = self._make_results([0.8, 0.6, 0.4])
        row = await test_db.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality($1::jsonb, 3, 0.3)",
            results,
        )
        assert row["is_valid"] is True
        assert row["chunk_count"] == 3
        assert row["top_score"] == pytest.approx(0.8)
        errors = json.loads(row["errors"]) if isinstance(row["errors"], str) else row["errors"]
        assert errors == []

    @pytest.mark.asyncio
    async def test_too_few_chunks_fails(self, test_db):
        """Fewer than min_chunks triggers an error."""
        results = self._make_results([0.9, 0.5])
        row = await test_db.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality($1::jsonb, 3, 0.3)",
            results,
        )
        assert row["is_valid"] is False
        errors = json.loads(row["errors"]) if isinstance(row["errors"], str) else row["errors"]
        assert any("Too few chunks" in e for e in errors)

    @pytest.mark.asyncio
    async def test_low_top_score_fails(self, test_db):
        """Top score at or below threshold triggers an error."""
        results = self._make_results([0.3, 0.2, 0.1])
        row = await test_db.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality($1::jsonb, 3, 0.3)",
            results,
        )
        assert row["is_valid"] is False
        errors = json.loads(row["errors"]) if isinstance(row["errors"], str) else row["errors"]
        assert any("Top score too low" in e for e in errors)

    @pytest.mark.asyncio
    async def test_both_failures_reported(self, test_db):
        """Both too-few-chunks and low-score produce two errors."""
        results = self._make_results([0.1])
        row = await test_db.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality($1::jsonb, 3, 0.3)",
            results,
        )
        assert row["is_valid"] is False
        errors = json.loads(row["errors"]) if isinstance(row["errors"], str) else row["errors"]
        assert len(errors) == 2

    @pytest.mark.asyncio
    async def test_null_input_fails(self, test_db):
        """NULL search_results is handled gracefully."""
        row = await test_db.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality(NULL::jsonb, 3, 0.3)",
        )
        assert row["is_valid"] is False
        assert row["chunk_count"] == 0
        assert row["top_score"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_empty_array_fails(self, test_db):
        """Empty array fails on both count and score."""
        row = await test_db.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality('[]'::jsonb, 3, 0.3)",
        )
        assert row["is_valid"] is False
        assert row["chunk_count"] == 0

    @pytest.mark.asyncio
    async def test_missing_combined_score_defaults_zero(self, test_db):
        """Chunks without combined_score key default to 0.0."""
        results = json.dumps([{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}])
        row = await test_db.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality($1::jsonb, 3, 0.3)",
            results,
        )
        assert row["is_valid"] is False
        assert row["top_score"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_custom_thresholds(self, test_db):
        """Custom min_chunks and min_score are respected."""
        results = self._make_results([0.5, 0.4])
        row = await test_db.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality($1::jsonb, 2, 0.4)",
            results,
        )
        assert row["is_valid"] is True
        assert row["chunk_count"] == 2

    @pytest.mark.asyncio
    async def test_defaults_used_when_omitted(self, test_db):
        """Defaults (min_chunks=3, min_score=0.3) apply when args omitted."""
        results = self._make_results([0.5, 0.4, 0.35])
        row = await test_db.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality($1::jsonb)",
            results,
        )
        assert row["is_valid"] is True
