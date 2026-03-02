"""
Tests for typed slide validation (fn_validate_slide_structure with slide_type dispatch).

Each slide type has valid + invalid test cases to verify the type-aware G3 gate.
"""

import json

import pytest
import pytest_asyncio


class TestStatementValidation:

    @pytest.mark.asyncio
    async def test_valid_statement(self, test_db):
        slide = {
            "intent": "thesis",
            "title": "The DB IS the Control Plane",
            "bullets": [],
            "content_data": {
                "statement": "Postgres handles retrieval, validation, state, and audit",
                "subtitle": "The LLM only drafts",
            },
            "speaker_notes": "This is the core thesis of the entire talk about Postgres.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is True, f"Errors: {result['errors']}"

    @pytest.mark.asyncio
    async def test_statement_too_short(self, test_db):
        slide = {
            "intent": "thesis",
            "title": "Thesis",
            "bullets": [],
            "content_data": {"statement": "Short"},
            "speaker_notes": "This is enough speaker notes for the validation check to pass here.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False
        errors = json.loads(result["errors"]) if isinstance(result["errors"], str) else result["errors"]
        assert any("8 chars" in e.lower() or "statement" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_statement_with_bullets_fails(self, test_db):
        slide = {
            "intent": "thesis",
            "title": "Thesis",
            "bullets": ["Should not be here"],
            "content_data": {"statement": "Postgres handles all deterministic operations"},
            "speaker_notes": "This is the core thesis of the entire talk about Postgres.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False


class TestSplitValidation:

    @pytest.mark.asyncio
    async def test_valid_split(self, test_db):
        slide = {
            "intent": "comparison",
            "title": "Postgres vs Vector DBs",
            "bullets": [],
            "content_data": {
                "left_title": "Postgres",
                "left_items": ["ACID transactions", "SQL joins"],
                "right_title": "Vector DBs",
                "right_items": ["Billion-scale vectors", "Managed scaling"],
            },
            "speaker_notes": "This slide compares Postgres with specialized vector databases.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is True, f"Errors: {result['errors']}"

    @pytest.mark.asyncio
    async def test_split_unbalanced_fails(self, test_db):
        slide = {
            "intent": "comparison",
            "title": "Comparison",
            "bullets": [],
            "content_data": {
                "left_items": ["A", "B", "C"],
                "right_items": ["X"],
            },
            "speaker_notes": "This slide compares Postgres with specialized vector databases.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False


class TestFlowValidation:

    @pytest.mark.asyncio
    async def test_valid_flow(self, test_db):
        slide = {
            "intent": "gates",
            "title": "Control Gates",
            "bullets": [],
            "content_data": {
                "steps": [
                    {"label": "G1 Retrieval", "caption": "Enough context?"},
                    {"label": "G2 Citations", "caption": "Sources valid?"},
                    {"label": "G2.5 Grounding", "caption": "Bullets match?"},
                    {"label": "G3 Format", "caption": "Structure OK?"},
                    {"label": "G4 Novelty", "caption": "Not duplicate?"},
                ]
            },
            "speaker_notes": "Each gate catches a different type of quality issue in the pipeline.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is True, f"Errors: {result['errors']}"

    @pytest.mark.asyncio
    async def test_flow_too_few_steps(self, test_db):
        slide = {
            "intent": "gates",
            "title": "Gates",
            "bullets": [],
            "content_data": {
                "steps": [
                    {"label": "G1", "caption": "One"},
                    {"label": "G2", "caption": "Two"},
                ]
            },
            "speaker_notes": "Each gate catches a different type of quality issue in the pipeline.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False


class TestDiagramValidation:

    @pytest.mark.asyncio
    async def test_valid_diagram(self, test_db):
        slide = {
            "intent": "architecture",
            "title": "System Architecture",
            "bullets": [],
            "content_data": {
                "callouts": ["Postgres central hub", "MCP typed boundary"],
                "caption": "Components interconnect through the database",
            },
            "speaker_notes": "This diagram shows how all system components connect through Postgres.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is True, f"Errors: {result['errors']}"

    @pytest.mark.asyncio
    async def test_diagram_too_many_callouts(self, test_db):
        slide = {
            "intent": "architecture",
            "title": "Architecture",
            "bullets": [],
            "content_data": {
                "callouts": ["A", "B", "C", "D"],
            },
            "speaker_notes": "This diagram shows how all system components connect through Postgres.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False


class TestCodeValidation:

    @pytest.mark.asyncio
    async def test_valid_code(self, test_db):
        code = "SELECT\n  c.content,\n  c.doc_title,\n  1 - (c.embedding <=> $1) AS score\nFROM chunk c\nWHERE 1 - (c.embedding <=> $1) > 0.5\nORDER BY score DESC\nLIMIT 10;"
        slide = {
            "intent": "rag-in-postgres",
            "title": "RAG Inside Postgres",
            "bullets": [],
            "content_data": {
                "language": "sql",
                "code_block": code,
                "explain_bullets": ["Hybrid search with pgvector"],
            },
            "speaker_notes": "This shows how we do semantic search directly inside Postgres.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is True, f"Errors: {result['errors']}"

    @pytest.mark.asyncio
    async def test_code_missing_language(self, test_db):
        slide = {
            "intent": "rag-in-postgres",
            "title": "RAG",
            "bullets": [],
            "content_data": {
                "code_block": "SELECT 1;\nSELECT 2;\nSELECT 3;\nSELECT 4;",
            },
            "speaker_notes": "This shows how we do semantic search directly inside Postgres.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False
        errors = json.loads(result["errors"]) if isinstance(result["errors"], str) else result["errors"]
        assert any("language" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_code_too_short(self, test_db):
        slide = {
            "intent": "rag-in-postgres",
            "title": "RAG",
            "bullets": [],
            "content_data": {
                "language": "sql",
                "code_block": "SELECT 1;",
            },
            "speaker_notes": "This shows how we do semantic search directly inside Postgres.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False
        errors = json.loads(result["errors"]) if isinstance(result["errors"], str) else result["errors"]
        assert any("short" in e.lower() or "min 4" in e.lower() for e in errors)


class TestBulletsValidation:
    """Bullets type should still work as before."""

    @pytest.mark.asyncio
    async def test_valid_bullets(self, test_db):
        slide = {
            "intent": "problem",
            "title": "The AI Problem",
            "bullets": ["Database sprawl hurts", "No transactions"],
            "speaker_notes": "This slide introduces the core problem we are addressing.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is True, f"Errors: {result['errors']}"

    @pytest.mark.asyncio
    async def test_bullets_too_many(self, test_db):
        slide = {
            "intent": "problem",
            "title": "Problem",
            "bullets": ["A", "B", "C", "D"],
            "speaker_notes": "This slide introduces the core problem we are addressing.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False


class TestGlobalChecks:
    """Title and speaker notes checks apply to all types."""

    @pytest.mark.asyncio
    async def test_title_too_long(self, test_db):
        slide = {
            "intent": "problem",
            "title": "A" * 65,
            "bullets": ["B1", "B2"],
            "speaker_notes": "This slide introduces the core problem we are addressing.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False
        errors = json.loads(result["errors"]) if isinstance(result["errors"], str) else result["errors"]
        assert any("title" in e.lower() and "long" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_title_trailing_period(self, test_db):
        slide = {
            "intent": "problem",
            "title": "This title ends with a period.",
            "bullets": ["B1", "B2"],
            "speaker_notes": "This slide introduces the core problem we are addressing.",
        }
        result = await test_db.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1::jsonb)",
            json.dumps(slide),
        )
        assert result["is_valid"] is False
        errors = json.loads(result["errors"]) if isinstance(result["errors"], str) else result["errors"]
        assert any("period" in e.lower() for e in errors)
