"""
SQL-level tests for image search functions.

Tests fn_search_images and image_asset table constraints
against a real Postgres database.
"""

import json
from uuid import uuid4

import pytest
import pytest_asyncio

from tests.conftest import get_test_embedding, get_test_image_asset


@pytest.mark.integration
class TestFnSearchImages:
    """Tests for fn_search_images SQL function."""

    @pytest.mark.asyncio
    async def test_fn_search_images_basic(self, seeded_db_with_images):
        """Basic search should return ranked results."""
        conn = seeded_db_with_images
        
        # Search with an embedding similar to the RAG architecture image
        query_embedding = get_test_embedding("RAG architecture pipeline diagram")
        
        rows = await conn.fetch(
            "SELECT * FROM fn_search_images($1, $2, $3)",
            str(query_embedding),
            "{}",
            5,
        )
        
        assert len(rows) > 0
        # Results should have required fields
        first = rows[0]
        assert first["image_id"] is not None
        assert first["storage_path"] is not None
        assert first["caption"] is not None
        assert first["similarity"] is not None
        # Similarity should be a float between 0 and 1
        assert 0 <= first["similarity"] <= 1

    @pytest.mark.asyncio
    async def test_fn_search_images_with_filters(self, seeded_db_with_images):
        """Search with style filter should return only matching styles."""
        conn = seeded_db_with_images
        
        query_embedding = get_test_embedding("test query for images")
        
        # Search with style filter for diagram
        rows = await conn.fetch(
            "SELECT * FROM fn_search_images($1, $2, $3)",
            str(query_embedding),
            json.dumps({"style": "diagram"}),
            5,
        )
        
        # All results should be diagrams
        for row in rows:
            assert row["style"] == "diagram"

    @pytest.mark.asyncio
    async def test_fn_search_images_no_results(self, seeded_db_with_images):
        """Search with impossible filter should return empty."""
        conn = seeded_db_with_images
        
        query_embedding = get_test_embedding("something unrelated")
        
        # Search with a style that doesn't exist in any data
        rows = await conn.fetch(
            "SELECT * FROM fn_search_images($1, $2, $3)",
            str(query_embedding),
            json.dumps({"style": "watercolor_painting"}),
            5,
        )
        
        assert len(rows) == 0


@pytest.mark.integration
class TestImageAssetConstraints:
    """Tests for image_asset table constraints."""

    @pytest.mark.asyncio
    async def test_image_asset_requires_doc_id(self, test_db):
        """image_asset should require a valid doc_id FK."""
        with pytest.raises(Exception):  # ForeignKeyViolationError
            await test_db.execute("""
                INSERT INTO image_asset (doc_id, storage_path, caption, alt_text, license, attribution)
                VALUES ($1, 'test.png', 'caption', 'alt', 'MIT', 'Author')
            """, uuid4())  # Random UUID - no matching doc

    @pytest.mark.asyncio
    async def test_image_asset_requires_license(self, test_db):
        """image_asset should require license field."""
        # Create a doc first
        doc_id = await test_db.fetchval("""
            INSERT INTO doc (doc_type, title, trust_level)
            VALUES ('image', 'Test', 'high')
            RETURNING doc_id
        """)
        
        with pytest.raises(Exception):  # NotNullViolation
            await test_db.execute("""
                INSERT INTO image_asset (doc_id, storage_path, caption, alt_text, attribution)
                VALUES ($1, 'test.png', 'caption', 'alt', 'Author')
            """, doc_id)  # Missing license

    @pytest.mark.asyncio
    async def test_slide_image_id_fk(self, seeded_db_with_images):
        """slide.image_id should reference image_asset."""
        conn = seeded_db_with_images
        
        # Get an image_id
        image_id = await conn.fetchval("SELECT image_id FROM image_asset LIMIT 1")
        assert image_id is not None
        
        # Create a deck and slide with image_id
        deck_id = await conn.fetchval("""
            SELECT fn_create_deck('Test Deck', 14, '{}'::jsonb, 'Test')
        """)
        
        # Insert a slide with image_id should work
        await conn.execute("""
            INSERT INTO slide (deck_id, slide_no, intent, title, bullets, image_id)
            VALUES ($1, 1, 'problem', 'Test Slide', '["bullet1"]'::jsonb, $2)
        """, deck_id, image_id)
        
        # Verify the slide has the image_id
        result = await conn.fetchval("""
            SELECT image_id FROM slide WHERE deck_id = $1 AND slide_no = 1
        """, deck_id)
        
        assert result == image_id
