"""
Tests for slide validation SQL functions.

Covers:
- fn_validate_slide_structure (G3 gate)
- fn_validate_citations (G2 gate)
"""

import json

import pytest
import pytest_asyncio


class TestValidateSlideStructure:
    """Tests for fn_validate_slide_structure."""
    
    @pytest.mark.asyncio
    async def test_valid_slide_passes(self, test_db):
        """A properly formatted slide passes validation (2-3 bullets, max 15 words)."""
        valid_slide = {
            "intent": "problem",
            "title": "The Problem Statement",
            "bullets": [
                "First important point",
                "Second key insight",
                "Third supporting argument",
            ],
            "speaker_notes": "This slide introduces the core problem we're addressing. It sets up the context for the solution."
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1::jsonb)
        """, json.dumps(valid_slide))
        
        assert result['is_valid'] is True, f"Valid slide should pass: {result['errors']}"
        errors_list = json.loads(result['errors']) if isinstance(result['errors'], str) else result['errors']
        assert errors_list == [], "Should have no errors"
    
    @pytest.mark.asyncio
    async def test_missing_title_fails(self, test_db):
        """Missing title fails validation."""
        slide = {
            "intent": "problem",
            "title": "",
            "bullets": ["One", "Two", "Three"],
            "speaker_notes": "Enough speaker notes to pass that check."
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is False
        errors_list = json.loads(result['errors'])
        assert any("title" in e.lower() for e in errors_list)
    
    @pytest.mark.asyncio
    async def test_two_bullets_passes(self, test_db):
        """Two bullets now passes validation (min is 2)."""
        slide = {
            "intent": "problem",
            "title": "Valid Title",
            "bullets": ["First point here", "Second point here"],
            "speaker_notes": "Sufficient speaker notes for the validation check."
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is True, f"Two bullets should pass: {result['errors']}"

    @pytest.mark.asyncio
    async def test_too_few_bullets_fails(self, test_db):
        """Less than 2 bullets fails validation."""
        slide = {
            "intent": "problem",
            "title": "Valid Title",
            "bullets": ["Only one"],
            "speaker_notes": "Sufficient speaker notes for the validation check."
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is False
        errors_list = json.loads(result['errors'])
        assert any("bullet" in e.lower() for e in errors_list)
    
    @pytest.mark.asyncio
    async def test_four_bullets_fails(self, test_db):
        """Four bullets now fails validation (max is 3)."""
        slide = {
            "intent": "problem",
            "title": "Valid Title",
            "bullets": ["One point", "Two point", "Three point", "Four point"],
            "speaker_notes": "Sufficient speaker notes for the validation check."
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is False
        errors_list = json.loads(result['errors'])
        assert any("bullet" in e.lower() for e in errors_list)

    @pytest.mark.asyncio
    async def test_too_many_bullets_fails(self, test_db):
        """More than 3 bullets fails validation."""
        slide = {
            "intent": "problem",
            "title": "Valid Title",
            "bullets": ["One", "Two", "Three", "Four", "Five", "Six"],
            "speaker_notes": "Sufficient speaker notes for the validation check."
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is False
        errors_list = json.loads(result['errors'])
        assert any("bullet" in e.lower() for e in errors_list)
    
    @pytest.mark.asyncio
    async def test_bullet_too_long_fails(self, test_db):
        """Bullets exceeding word limit fail validation."""
        long_bullet = " ".join(["word"] * 20)  # 20 words, exceeds 15 limit
        slide = {
            "intent": "problem",
            "title": "Valid Title",
            "bullets": [
                "Short bullet",
                long_bullet,
                "Another short one",
            ],
            "speaker_notes": "Sufficient speaker notes for the validation check."
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is False
        errors_list = json.loads(result['errors'])
        assert any("long" in e.lower() or "word" in e.lower() for e in errors_list)
    
    @pytest.mark.asyncio
    async def test_missing_speaker_notes_fails_for_content_slides(self, test_db):
        """Content slides require speaker notes."""
        slide = {
            "intent": "architecture",  # Content slide, not title/thanks
            "title": "System Architecture",
            "bullets": ["Point one", "Point two", "Point three"],
            "speaker_notes": ""  # Empty notes
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is False
        errors_list = json.loads(result['errors'])
        assert any("notes" in e.lower() for e in errors_list)
    
    @pytest.mark.asyncio
    async def test_title_slide_skips_notes_requirement(self, test_db):
        """Title slides don't require speaker notes."""
        slide = {
            "intent": "title",
            "title": "Presentation Title",
            "bullets": ["Subtitle point", "Another point", "Third point"],
            "speaker_notes": ""  # Empty is OK for title slides
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_slide_structure($1::jsonb)
        """, json.dumps(slide))
        
        # Should only fail for other reasons, not speaker notes
        if not result['is_valid']:
            errors_list = json.loads(result['errors'])
            assert not any("notes" in e.lower() for e in errors_list)


class TestValidateCitations:
    """Tests for fn_validate_citations."""
    
    @pytest.mark.asyncio
    async def test_valid_citations_pass(self, seeded_db):
        """Valid citations referencing real chunks pass."""
        # Get a real chunk_id from seeded data
        chunk = await seeded_db.fetchrow("SELECT chunk_id FROM chunk LIMIT 1")
        
        slide = {
            "citations": [
                {"chunk_id": str(chunk['chunk_id']), "title": "Test Source"}
            ]
        }
        
        result = await seeded_db.fetchrow("""
            SELECT * FROM fn_validate_citations($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is True
        assert result['citation_count'] == 1
    
    @pytest.mark.asyncio
    async def test_missing_citations_fails(self, test_db):
        """No citations fails validation."""
        slide = {"citations": []}
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_citations($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is False
        assert result['citation_count'] == 0
    
    @pytest.mark.asyncio
    async def test_invalid_chunk_id_fails(self, test_db):
        """Citations with non-existent chunk_ids fail."""
        from uuid import uuid4
        
        slide = {
            "citations": [
                {"chunk_id": str(uuid4()), "title": "Fake Source"}
            ]
        }
        
        result = await test_db.fetchrow("""
            SELECT * FROM fn_validate_citations($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is False
        errors_list = json.loads(result['errors'])
        assert any("non-existent" in e.lower() or "chunk" in e.lower() for e in errors_list)
    
    @pytest.mark.asyncio
    async def test_multiple_valid_citations(self, seeded_db):
        """Multiple valid citations all verified."""
        chunks = await seeded_db.fetch("SELECT chunk_id FROM chunk LIMIT 3")
        
        slide = {
            "citations": [
                {"chunk_id": str(c['chunk_id']), "title": f"Source {i}"}
                for i, c in enumerate(chunks)
            ]
        }
        
        result = await seeded_db.fetchrow("""
            SELECT * FROM fn_validate_citations($1::jsonb)
        """, json.dumps(slide))
        
        assert result['is_valid'] is True
        assert result['citation_count'] == len(chunks)
    
    @pytest.mark.asyncio
    async def test_custom_min_citations(self, seeded_db):
        """Custom minimum citation requirement enforced."""
        chunk = await seeded_db.fetchrow("SELECT chunk_id FROM chunk LIMIT 1")
        
        slide = {
            "citations": [
                {"chunk_id": str(chunk['chunk_id']), "title": "Only One"}
            ]
        }
        
        # Require 3 citations
        result = await seeded_db.fetchrow("""
            SELECT * FROM fn_validate_citations($1::jsonb, 3)
        """, json.dumps(slide))
        
        assert result['is_valid'] is False
        assert result['citation_count'] == 1
