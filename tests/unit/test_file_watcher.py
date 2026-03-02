"""
Unit tests for the file watcher (Kafka producer).

Tests:
- Extension filtering (only .md, images, .json)
- Directory filtering (.md only from content/external/)
- Debounce logic
- Publish payload format
- Ignores delete events and directories
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.file_watcher import ContentChangeHandler, ALL_EXTENSIONS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_producer():
    producer = MagicMock()
    producer.send = MagicMock()
    producer.flush = MagicMock()
    return producer


@pytest.fixture
def handler(mock_producer):
    return ContentChangeHandler(producer=mock_producer, topic="content.changes")


def _make_event(src_path, is_directory=False):
    event = MagicMock()
    event.src_path = src_path
    event.is_directory = is_directory
    return event


# ---------------------------------------------------------------------------
# Extension Filtering
# ---------------------------------------------------------------------------

class TestExtensionFiltering:
    def test_accepts_markdown(self, handler):
        assert handler._should_handle("content/external/rag.md")

    def test_accepts_png(self, handler):
        assert handler._should_handle("content/images/arch.png")

    def test_accepts_jpg(self, handler):
        assert handler._should_handle("content/images/photo.jpg")

    def test_accepts_json_sidecar(self, handler):
        assert handler._should_handle("content/images/arch.json")

    def test_accepts_svg(self, handler):
        assert handler._should_handle("content/images/diagram.svg")

    def test_rejects_python(self, handler):
        assert not handler._should_handle("src/ingest.py")

    def test_rejects_html(self, handler):
        assert not handler._should_handle("output/deck.html")

    def test_rejects_txt(self, handler):
        assert not handler._should_handle("notes.txt")


# ---------------------------------------------------------------------------
# Directory Filtering (md only from external/)
# ---------------------------------------------------------------------------

class TestDirectoryFiltering:
    def test_md_in_external_accepted(self, handler):
        assert handler._should_handle("content/external/rag.md")

    def test_md_outside_external_rejected(self, handler):
        assert not handler._should_handle("docs/architecture.md")

    def test_md_in_root_rejected(self, handler):
        assert not handler._should_handle("README.md")

    def test_images_accepted_regardless(self, handler):
        assert handler._should_handle("content/images/photo.png")


# ---------------------------------------------------------------------------
# Debounce Logic
# ---------------------------------------------------------------------------

class TestDebounce:
    def test_first_event_not_debounced(self, handler):
        assert not handler._is_debounced("content/external/new.md")

    def test_rapid_duplicate_is_debounced(self, handler):
        handler._is_debounced("content/external/rag.md")
        assert handler._is_debounced("content/external/rag.md")

    def test_different_files_not_debounced(self, handler):
        handler._is_debounced("content/external/a.md")
        assert not handler._is_debounced("content/external/b.md")

    def test_after_cooldown_not_debounced(self, handler):
        handler._is_debounced("content/external/rag.md")
        handler._last_seen["content/external/rag.md"] = time.monotonic() - 5.0
        assert not handler._is_debounced("content/external/rag.md")


# ---------------------------------------------------------------------------
# Publish Payload
# ---------------------------------------------------------------------------

class TestPublish:
    def test_publish_sends_json_to_topic(self, handler, mock_producer):
        handler._publish("content/external/rag.md", "created")

        mock_producer.send.assert_called_once()
        call_kwargs = mock_producer.send.call_args
        assert call_kwargs[0][0] == "content.changes"

        payload = json.loads(call_kwargs[1]["value"].decode("utf-8"))
        assert payload["path"] == "content/external/rag.md"
        assert payload["event_type"] == "created"
        assert "timestamp" in payload

    def test_publish_uses_path_as_key(self, handler, mock_producer):
        handler._publish("content/images/arch.png", "modified")

        call_kwargs = mock_producer.send.call_args
        assert call_kwargs[1]["key"] == b"content/images/arch.png"

    def test_publish_flushes(self, handler, mock_producer):
        handler._publish("content/external/rag.md", "created")
        mock_producer.flush.assert_called_once()


# ---------------------------------------------------------------------------
# Event Handler Callbacks
# ---------------------------------------------------------------------------

class TestEventCallbacks:
    def test_on_created_publishes(self, handler, mock_producer):
        event = _make_event("content/external/new.md")
        handler.on_created(event)
        mock_producer.send.assert_called_once()

    def test_on_modified_publishes(self, handler, mock_producer):
        event = _make_event("content/external/updated.md")
        handler.on_modified(event)
        mock_producer.send.assert_called_once()

    def test_directory_event_ignored(self, handler, mock_producer):
        event = _make_event("content/external/", is_directory=True)
        handler.on_created(event)
        mock_producer.send.assert_not_called()

    def test_unsupported_extension_ignored(self, handler, mock_producer):
        event = _make_event("src/ingest.py")
        handler.on_created(event)
        mock_producer.send.assert_not_called()

    def test_debounced_event_not_published(self, handler, mock_producer):
        event = _make_event("content/external/rag.md")
        handler.on_created(event)
        mock_producer.send.reset_mock()
        handler.on_modified(event)
        mock_producer.send.assert_not_called()
