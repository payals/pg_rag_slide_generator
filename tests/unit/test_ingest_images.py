"""
Unit tests for image ingestion pipeline.

Tests validation, parsing, hashing, and error handling
for the image ingestion workflow.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ingest_images import (
    compute_image_hash,
    find_images,
    load_metadata,
    SUPPORTED_EXTENSIONS,
)
from src.models import ImageMetadata
from tests.conftest import get_test_image_metadata


class TestParseMetadata:
    """Tests for ImageMetadata Pydantic validation."""

    def test_parse_valid_metadata(self):
        """Valid JSON metadata should parse without errors."""
        data = get_test_image_metadata()
        metadata = ImageMetadata(**data)
        
        assert metadata.caption == data["caption"]
        assert metadata.alt_text == data["alt_text"]
        assert metadata.license == data["license"]
        assert metadata.attribution == data["attribution"]
        assert metadata.style == "diagram"
        assert metadata.use_cases == data["use_cases"]

    def test_parse_metadata_missing_license_fails(self):
        """Missing license should fail validation."""
        data = get_test_image_metadata()
        del data["license"]
        
        with pytest.raises(Exception):  # ValidationError
            ImageMetadata(**data)

    def test_parse_metadata_missing_attribution_fails(self):
        """Missing attribution should fail validation."""
        data = get_test_image_metadata()
        del data["attribution"]
        
        with pytest.raises(Exception):  # ValidationError
            ImageMetadata(**data)

    def test_parse_metadata_empty_caption_fails(self):
        """Caption shorter than min_length (10) should fail validation."""
        data = get_test_image_metadata({"caption": "Short"})
        
        with pytest.raises(Exception):  # ValidationError
            ImageMetadata(**data)

    def test_parse_metadata_short_alt_text_fails(self):
        """Alt text shorter than min_length (5) should fail validation."""
        data = get_test_image_metadata({"alt_text": "Hi"})
        
        with pytest.raises(Exception):  # ValidationError
            ImageMetadata(**data)

    def test_parse_metadata_optional_style(self):
        """Style should be optional."""
        data = get_test_image_metadata()
        del data["style"]
        
        metadata = ImageMetadata(**data)
        assert metadata.style is None

    def test_parse_metadata_invalid_style(self):
        """Invalid style enum value should fail."""
        data = get_test_image_metadata({"style": "invalid_style"})
        
        with pytest.raises(Exception):
            ImageMetadata(**data)

    def test_parse_metadata_empty_use_cases(self):
        """Empty use_cases list should be valid."""
        data = get_test_image_metadata({"use_cases": []})
        
        metadata = ImageMetadata(**data)
        assert metadata.use_cases == []

    def test_parse_metadata_unicode_caption(self):
        """Unicode in caption should be valid."""
        data = get_test_image_metadata({"caption": "Diagramm: RAG-Architektur für KI-Anwendungen"})
        
        metadata = ImageMetadata(**data)
        assert "Architektur" in metadata.caption

    def test_parse_metadata_long_caption(self):
        """Very long caption should be valid."""
        long_caption = "A" * 1000 + " diagram showing architecture"
        data = get_test_image_metadata({"caption": long_caption})
        
        metadata = ImageMetadata(**data)
        assert len(metadata.caption) > 1000


class TestComputeHash:
    """Tests for image file hashing."""

    def test_compute_image_hash(self):
        """Hash should be deterministic for same content."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake image content")
            f.flush()
            
            hash1 = compute_image_hash(Path(f.name))
            hash2 = compute_image_hash(Path(f.name))
            
            assert hash1 == hash2
            assert len(hash1) == 64  # SHA-256 hex length

    def test_different_content_different_hash(self):
        """Different content should produce different hashes."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f1:
            f1.write(b"content A")
            f1.flush()
            
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f2:
                f2.write(b"content B")
                f2.flush()
                
                hash1 = compute_image_hash(Path(f1.name))
                hash2 = compute_image_hash(Path(f2.name))
                
                assert hash1 != hash2


class TestFindImages:
    """Tests for image discovery."""

    def test_find_images_in_directory(self, tmp_path):
        """Should find supported image files."""
        # Create test files
        (tmp_path / "test1.png").write_bytes(b"png")
        (tmp_path / "test2.jpg").write_bytes(b"jpg")
        (tmp_path / "test3.svg").write_bytes(b"svg")
        (tmp_path / "readme.txt").write_text("not an image")
        
        images = find_images(tmp_path)
        
        names = {img.name for img in images}
        assert "test1.png" in names
        assert "test2.jpg" in names
        assert "test3.svg" in names
        assert "readme.txt" not in names

    def test_find_images_empty_directory(self, tmp_path):
        """Empty directory should return empty list."""
        images = find_images(tmp_path)
        assert images == []

    def test_find_images_nonexistent_directory(self):
        """Nonexistent directory should return empty list."""
        images = find_images(Path("/nonexistent/path"))
        assert images == []

    def test_find_single_image(self, tmp_path):
        """Single path mode should only return that file."""
        (tmp_path / "target.png").write_bytes(b"png")
        (tmp_path / "other.png").write_bytes(b"png")
        
        images = find_images(tmp_path, single_path=tmp_path / "target.png")
        
        assert len(images) == 1
        assert images[0].name == "target.png"

    def test_find_single_image_not_found(self, tmp_path):
        """Single path mode with missing file should return empty."""
        images = find_images(tmp_path, single_path=tmp_path / "missing.png")
        assert images == []


class TestLoadMetadata:
    """Tests for JSON sidecar file loading."""

    def test_load_valid_metadata(self, tmp_path):
        """Valid JSON sidecar should load correctly."""
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"png")
        
        json_path = tmp_path / "test.json"
        json_path.write_text(json.dumps(get_test_image_metadata()))
        
        metadata = load_metadata(img_path)
        
        assert metadata is not None
        assert metadata.caption == get_test_image_metadata()["caption"]

    def test_skip_image_without_json(self, tmp_path):
        """Image without JSON sidecar should return None."""
        img_path = tmp_path / "no_metadata.png"
        img_path.write_bytes(b"png")
        
        metadata = load_metadata(img_path)
        assert metadata is None

    def test_skip_invalid_json(self, tmp_path):
        """Invalid JSON should return None."""
        img_path = tmp_path / "bad.png"
        img_path.write_bytes(b"png")
        
        json_path = tmp_path / "bad.json"
        json_path.write_text("{invalid json}")
        
        metadata = load_metadata(img_path)
        assert metadata is None

    def test_skip_json_missing_required_fields(self, tmp_path):
        """JSON missing required fields should return None."""
        img_path = tmp_path / "incomplete.png"
        img_path.write_bytes(b"png")
        
        json_path = tmp_path / "incomplete.json"
        json_path.write_text(json.dumps({"caption": "Only caption, no license"}))
        
        metadata = load_metadata(img_path)
        assert metadata is None

    def test_dry_run_output_format(self, tmp_path):
        """Dry run should not fail with valid metadata."""
        # This tests that load_metadata works independently of ingestion
        img_path = tmp_path / "dry.png"
        img_path.write_bytes(b"png data")
        
        json_path = tmp_path / "dry.json"
        json_path.write_text(json.dumps(get_test_image_metadata()))
        
        metadata = load_metadata(img_path)
        assert metadata is not None
        assert isinstance(metadata.caption, str)
        assert isinstance(metadata.license, str)
