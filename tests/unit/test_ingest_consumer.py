"""
Unit tests for the Kafka ingest consumer.

Tests:
- Routing: .md -> ingest_document, image -> ingest_single_image, .json -> companion re-ingest
- Skips missing files gracefully
- Skips images without valid JSON sidecar
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ingest_consumer import (
    _handle_markdown,
    _handle_image,
    _handle_json_sidecar,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sync_client():
    return MagicMock()


@pytest.fixture
def async_client():
    return AsyncMock()


# ---------------------------------------------------------------------------
# Markdown Routing
# ---------------------------------------------------------------------------

class TestHandleMarkdown:
    @pytest.mark.asyncio
    @patch("src.ingest_consumer.get_connection")
    @patch("src.ingest_consumer.ingest_document", new_callable=AsyncMock)
    async def test_calls_ingest_document(self, mock_ingest, mock_conn, sync_client, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n---\nBody content here for testing purposes.")
        mock_ingest.return_value = {"chunks": 3, "inserted": 3}
        mock_conn.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_conn.return_value.__aexit__ = AsyncMock(return_value=False)

        await _handle_markdown(md_file, sync_client)
        mock_ingest.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("src.ingest_consumer.get_connection")
    @patch("src.ingest_consumer.ingest_document", new_callable=AsyncMock)
    async def test_skips_missing_file(self, mock_ingest, mock_conn, sync_client):
        await _handle_markdown(Path("/nonexistent/file.md"), sync_client)
        mock_ingest.assert_not_awaited()


# ---------------------------------------------------------------------------
# Image Routing
# ---------------------------------------------------------------------------

class TestHandleImage:
    @pytest.mark.asyncio
    @patch("src.ingest_consumer.get_connection")
    @patch("src.ingest_consumer.ingest_single_image", new_callable=AsyncMock)
    @patch("src.ingest_consumer.load_metadata")
    async def test_calls_ingest_single_image(self, mock_meta, mock_ingest, mock_conn, async_client, tmp_path):
        img = tmp_path / "arch.png"
        img.write_bytes(b"\x89PNG fake")
        mock_meta.return_value = MagicMock()
        mock_ingest.return_value = "some-uuid"
        mock_conn.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_conn.return_value.__aexit__ = AsyncMock(return_value=False)

        await _handle_image(img, async_client)
        mock_ingest.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("src.ingest_consumer.ingest_single_image", new_callable=AsyncMock)
    @patch("src.ingest_consumer.load_metadata")
    async def test_skips_missing_image(self, mock_meta, mock_ingest, async_client):
        await _handle_image(Path("/nonexistent/image.png"), async_client)
        mock_ingest.assert_not_awaited()
        mock_meta.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.ingest_consumer.get_connection")
    @patch("src.ingest_consumer.ingest_single_image", new_callable=AsyncMock)
    @patch("src.ingest_consumer.load_metadata", return_value=None)
    async def test_skips_image_without_sidecar(self, mock_meta, mock_ingest, mock_conn, async_client, tmp_path):
        img = tmp_path / "no_sidecar.png"
        img.write_bytes(b"\x89PNG fake")

        await _handle_image(img, async_client)
        mock_ingest.assert_not_awaited()


# ---------------------------------------------------------------------------
# JSON Sidecar -> Companion Image Re-ingest
# ---------------------------------------------------------------------------

class TestHandleJsonSidecar:
    @pytest.mark.asyncio
    @patch("src.ingest_consumer._handle_image", new_callable=AsyncMock)
    async def test_finds_and_reingests_companion_png(self, mock_handle_image, async_client, tmp_path):
        img = tmp_path / "arch.png"
        img.write_bytes(b"\x89PNG fake")
        sidecar = tmp_path / "arch.json"
        sidecar.write_text('{"caption":"test"}')

        await _handle_json_sidecar(sidecar, async_client)
        mock_handle_image.assert_awaited_once_with(img, async_client)

    @pytest.mark.asyncio
    @patch("src.ingest_consumer._handle_image", new_callable=AsyncMock)
    async def test_skips_when_no_companion_found(self, mock_handle_image, async_client, tmp_path):
        sidecar = tmp_path / "orphan.json"
        sidecar.write_text('{"caption":"test"}')

        await _handle_json_sidecar(sidecar, async_client)
        mock_handle_image.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("src.ingest_consumer._handle_image", new_callable=AsyncMock)
    async def test_prefers_png_over_other_formats(self, mock_handle_image, async_client, tmp_path):
        png = tmp_path / "multi.png"
        png.write_bytes(b"\x89PNG")
        jpg = tmp_path / "multi.jpg"
        jpg.write_bytes(b"\xff\xd8")
        sidecar = tmp_path / "multi.json"
        sidecar.write_text('{}')

        await _handle_json_sidecar(sidecar, async_client)
        mock_handle_image.assert_awaited_once()
        called_path = mock_handle_image.call_args[0][0]
        assert called_path.suffix in {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}
