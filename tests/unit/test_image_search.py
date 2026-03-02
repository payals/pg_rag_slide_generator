"""
Unit tests for image search MCP tools.

Tests search_images, get_image, and validate_image tools
using mocked database connections and embeddings.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tests.conftest import get_test_image_asset


# We test the MCP tool implementations directly
# Since they depend on DB connections, we mock those


class TestSearchImages:
    """Tests for search_images tool."""

    @pytest.mark.asyncio
    async def test_search_images_returns_ranked_results(self):
        """Search should return results ranked by similarity."""
        mock_rows = [
            {
                "image_id": uuid4(),
                "storage_path": "diagram1.png",
                "caption": "RAG architecture diagram",
                "alt_text": "Diagram of RAG",
                "use_cases": ["architecture"],
                "style": "diagram",
                "similarity": 0.95,
            },
            {
                "image_id": uuid4(),
                "storage_path": "diagram2.png",
                "caption": "MCP tools diagram",
                "alt_text": "Diagram of MCP",
                "use_cases": ["tools"],
                "style": "diagram",
                "similarity": 0.80,
            },
        ]
        
        with patch("src.mcp_server.get_embedding", new_callable=AsyncMock) as mock_embed, \
             patch("src.mcp_server.get_connection") as mock_conn_ctx:
            
            mock_embed.return_value = [0.1] * 1536
            
            mock_conn = AsyncMock()
            mock_conn.fetch = AsyncMock(return_value=mock_rows)
            mock_conn_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            
            from src.mcp_server import mcp_search_images
            results = await mcp_search_images("RAG architecture", top_k=5)
            
            assert len(results) == 2
            assert results[0]["similarity"] >= results[1]["similarity"]
            assert results[0]["storage_path"] == "diagram1.png"

    @pytest.mark.asyncio
    async def test_search_images_empty_results(self):
        """Search with no matches should return empty list."""
        with patch("src.mcp_server.get_embedding", new_callable=AsyncMock) as mock_embed, \
             patch("src.mcp_server.get_connection") as mock_conn_ctx:
            
            mock_embed.return_value = [0.1] * 1536
            
            mock_conn = AsyncMock()
            mock_conn.fetch = AsyncMock(return_value=[])
            mock_conn_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            
            from src.mcp_server import mcp_search_images
            results = await mcp_search_images("completely unrelated query", top_k=5)
            
            assert results == []

    @pytest.mark.asyncio
    async def test_search_images_with_style_filter(self):
        """Search with style filter should pass filter to DB."""
        with patch("src.mcp_server.get_embedding", new_callable=AsyncMock) as mock_embed, \
             patch("src.mcp_server.get_connection") as mock_conn_ctx:
            
            mock_embed.return_value = [0.1] * 1536
            
            mock_conn = AsyncMock()
            mock_conn.fetch = AsyncMock(return_value=[])
            mock_conn_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            
            from src.mcp_server import mcp_search_images
            await mcp_search_images("test query", filters={"style": "diagram"}, top_k=3)
            
            # Verify the fetch was called with filter JSON
            call_args = mock_conn.fetch.call_args
            filter_json = call_args[0][2]  # Third positional arg
            assert "diagram" in filter_json

    @pytest.mark.asyncio
    async def test_search_images_with_use_case_filter(self):
        """Search with use_case filter should pass to DB."""
        with patch("src.mcp_server.get_embedding", new_callable=AsyncMock) as mock_embed, \
             patch("src.mcp_server.get_connection") as mock_conn_ctx:
            
            mock_embed.return_value = [0.1] * 1536
            
            mock_conn = AsyncMock()
            mock_conn.fetch = AsyncMock(return_value=[])
            mock_conn_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            
            from src.mcp_server import mcp_search_images
            await mcp_search_images("test", filters={"use_cases": ["architecture"]})
            
            call_args = mock_conn.fetch.call_args
            filter_json = call_args[0][2]
            assert "architecture" in filter_json


class TestGetImage:
    """Tests for get_image tool."""

    @pytest.mark.asyncio
    async def test_get_image_by_id(self):
        """Should return full image metadata for valid ID."""
        image_id = uuid4()
        doc_id = uuid4()
        
        mock_row = {
            "image_id": image_id,
            "doc_id": doc_id,
            "storage_path": "test.png",
            "caption": "Test image",
            "alt_text": "Test alt",
            "use_cases": ["test"],
            "license": "CC-BY-4.0",
            "attribution": "Author",
            "style": "diagram",
            "width": 800,
            "height": 600,
            "created_at": None,
        }
        
        with patch("src.mcp_server.get_connection") as mock_conn_ctx:
            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(return_value=mock_row)
            mock_conn_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            
            from src.mcp_server import _get_image
            result = await _get_image(str(image_id))
            
            assert result["image_id"] == str(image_id)
            assert result["storage_path"] == "test.png"
            assert result["license"] == "CC-BY-4.0"
            assert result["width"] == 800

    @pytest.mark.asyncio
    async def test_get_image_not_found(self):
        """Should raise ValueError for non-existent image."""
        with patch("src.mcp_server.get_connection") as mock_conn_ctx:
            mock_conn = AsyncMock()
            mock_conn.fetchrow = AsyncMock(return_value=None)
            mock_conn_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            
            from src.mcp_server import _get_image
            
            with pytest.raises(ValueError, match="Image not found"):
                await _get_image(str(uuid4()))


class TestValidateImage:
    """Tests for validate_image G5 gate."""

    @pytest.mark.asyncio
    async def test_validate_image_passes(self, tmp_path):
        """Image with license, attribution, and existing file should pass."""
        image_id = uuid4()
        
        # Create a temp image file
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "test.png").write_bytes(b"fake png")
        
        mock_image = {
            "image_id": str(image_id),
            "doc_id": str(uuid4()),
            "storage_path": "test.png",
            "caption": "Test",
            "alt_text": "Test alt",
            "use_cases": [],
            "license": "CC-BY-4.0",
            "attribution": "Author",
            "style": "diagram",
            "width": 800,
            "height": 600,
        }
        
        with patch("src.mcp_server._get_image", new_callable=AsyncMock) as mock_get, \
             patch.dict(os.environ, {"IMAGE_CONTENT_DIR": str(img_dir)}):
            mock_get.return_value = mock_image
            
            from src.mcp_server import mcp_validate_image
            result = await mcp_validate_image(str(image_id))
            
            assert result["is_valid"] is True
            assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_validate_image_missing_license(self):
        """Image without license should fail validation."""
        mock_image = {
            "image_id": str(uuid4()),
            "doc_id": str(uuid4()),
            "storage_path": "test.png",
            "caption": "Test",
            "alt_text": "Test",
            "use_cases": [],
            "license": "",
            "attribution": "Author",
            "style": None,
            "width": None,
            "height": None,
        }
        
        with patch("src.mcp_server._get_image", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_image
            
            from src.mcp_server import mcp_validate_image
            result = await mcp_validate_image(str(uuid4()))
            
            assert result["is_valid"] is False
            assert any("license" in e.lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validate_image_missing_file_fails(self, tmp_path):
        """Image with missing file should fail validation."""
        mock_image = {
            "image_id": str(uuid4()),
            "doc_id": str(uuid4()),
            "storage_path": "nonexistent.png",
            "caption": "Test",
            "alt_text": "Test",
            "use_cases": [],
            "license": "CC-BY-4.0",
            "attribution": "Author",
            "style": None,
            "width": None,
            "height": None,
        }
        
        with patch("src.mcp_server._get_image", new_callable=AsyncMock) as mock_get, \
             patch.dict(os.environ, {"IMAGE_CONTENT_DIR": str(tmp_path)}):
            mock_get.return_value = mock_image
            
            from src.mcp_server import mcp_validate_image
            result = await mcp_validate_image(str(uuid4()))
            
            assert result["is_valid"] is False
            assert any("not found" in e.lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validate_image_not_found_in_db(self):
        """Non-existent image ID should fail validation."""
        with patch("src.mcp_server._get_image", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = ValueError("Image not found: fake-id")
            
            from src.mcp_server import mcp_validate_image
            result = await mcp_validate_image("fake-id")
            
            assert result["is_valid"] is False
            assert any("not found" in e.lower() for e in result["errors"])
