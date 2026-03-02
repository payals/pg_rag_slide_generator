"""
Unit tests for Run Report CLI (src/run_report.py).

Tests formatting functions and output structure.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from src.run_report import format_plain, build_full_report


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_report():
    """Sample report data matching fn_get_run_report output."""
    return {
        "deck_id": "test-deck-id",
        "topic": "Postgres as AI Application Server",
        "generated_at": "2026-02-07T12:00:00",
        "summary": {
            "total_slides": 12,
            "target_slides": 14,
            "coverage_pct": 85.7,
            "total_retries": 5,
        },
        "coverage": {
            "covered": ["problem", "why-postgres", "thesis", "architecture"],
            "missing": ["what-we-built", "takeaways"],
        },
        "gate_summary": {
            "g1_retrieval": {"pass": 12, "fail": 2},
            "g3_format": {"pass": 14, "fail": 1},
            "g4_novelty": {"pass": 12, "fail": 0},
        },
        "slides": [
            {"slide_no": 1, "intent": "problem", "title": "The AI Problem", "retry_count": 0},
            {"slide_no": 2, "intent": "why-postgres", "title": "Why Postgres", "retry_count": 1},
        ],
        "orchestrator_metrics": {
            "llm_calls": 20,
            "embeddings_generated": 50,
            "total_retries": 5,
            "slides_generated": 12,
            "failed_intents": [],
            "abandoned_intents": [],
            "images_deduplicated": 3,
            "fallback_triggered": False,
            "cost": {
                "prompt_tokens": 15000,
                "completion_tokens": 8000,
                "embedding_tokens": 5000,
                "estimated_cost_usd": 0.9301,
            },
        },
        "gate_failures": [],
        "top_sources": [
            {"doc_title": "Postgres AI Guide", "citation_count": 15},
        ],
    }


# =============================================================================
# PLAIN TEXT FORMATTING TESTS
# =============================================================================

class TestFormatPlain:
    """Tests for plain text report formatting."""
    
    def test_produces_output(self, sample_report):
        """Should produce non-empty output."""
        output = format_plain(sample_report)
        
        assert len(output) > 100
        assert "DECK GENERATION REPORT" in output
    
    def test_includes_deck_id(self, sample_report):
        """Should include deck ID in output."""
        output = format_plain(sample_report)
        
        assert "test-deck-id" in output
    
    def test_includes_summary(self, sample_report):
        """Should include summary section."""
        output = format_plain(sample_report)
        
        assert "12 / 14" in output
        assert "85.7%" in output
    
    def test_includes_cost(self, sample_report):
        """Should include cost section."""
        output = format_plain(sample_report)
        
        assert "15,000" in output or "15000" in output
        assert "0.9301" in output
    
    def test_includes_coverage(self, sample_report):
        """Should include coverage section."""
        output = format_plain(sample_report)
        
        assert "problem" in output
        assert "takeaways" in output
    
    def test_includes_gate_stats(self, sample_report):
        """Should include gate statistics."""
        output = format_plain(sample_report)
        
        assert "g1_retrieval" in output
        assert "g3_format" in output
    
    def test_verbose_includes_slides(self, sample_report):
        """Should include per-slide details when verbose=True."""
        output = format_plain(sample_report, verbose=True)
        
        assert "Per-Slide Details" in output
        assert "The AI Problem" in output
    
    def test_non_verbose_excludes_slides(self, sample_report):
        """Should not include per-slide details when verbose=False."""
        output = format_plain(sample_report, verbose=False)
        
        assert "Per-Slide Details" not in output
    
    def test_handles_empty_report(self):
        """Should handle empty/minimal report gracefully."""
        empty_report = {
            "deck_id": "empty",
            "summary": {},
            "coverage": {},
            "orchestrator_metrics": {},
        }
        
        output = format_plain(empty_report)
        
        assert "DECK GENERATION REPORT" in output
        assert "empty" in output
    
    def test_shows_fallback_triggered(self, sample_report):
        """Should show fallback warning when triggered."""
        sample_report["orchestrator_metrics"]["fallback_triggered"] = True
        sample_report["orchestrator_metrics"]["failed_intents"] = ["a", "b"]
        sample_report["orchestrator_metrics"]["abandoned_intents"] = ["c", "d"]
        
        output = format_plain(sample_report)
        
        assert "FALLBACK TRIGGERED" in output


# =============================================================================
# JSON OUTPUT TESTS
# =============================================================================

class TestJsonOutput:
    """Tests for JSON output mode."""
    
    def test_report_is_json_serializable(self, sample_report):
        """Report should be JSON-serializable."""
        output = json.dumps(sample_report, default=str)
        
        parsed = json.loads(output)
        assert parsed["deck_id"] == "test-deck-id"
    
    def test_json_has_all_sections(self, sample_report):
        """JSON output should contain all report sections."""
        output = json.dumps(sample_report, default=str)
        parsed = json.loads(output)
        
        assert "summary" in parsed
        assert "coverage" in parsed
        assert "gate_summary" in parsed
        assert "orchestrator_metrics" in parsed
