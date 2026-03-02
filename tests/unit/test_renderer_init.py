"""Tests for renderer initialization and accessor functions.

These tests mock the model-level caches to avoid DB dependency.
"""

import pytest
from unittest.mock import AsyncMock, patch

import src.renderer as renderer_mod
from src.renderer import (
    init_renderer,
    _check_initialized,
    get_intent_order,
    get_target_slides,
    get_title_slide,
    get_thanks_slide,
    get_section_dividers,
    get_divider_images,
    get_themes,
)


@pytest.fixture(autouse=True)
def reset_init_flag():
    """Reset _initialized before each test."""
    renderer_mod._initialized = False
    yield
    renderer_mod._initialized = False


@pytest.fixture
def mock_loaders():
    """Mock all four loader functions and populate caches."""
    import src.models as models

    old_itm = models.INTENT_TYPE_MAP.copy()
    old_ss = models.STATIC_SLIDES.copy()
    old_sd = models.SECTION_DIVIDERS_CACHE[:]
    old_tc = models.THEMES_CACHE.copy()

    from src.models import IntentTypeInfo

    models.INTENT_TYPE_MAP.clear()
    models.INTENT_TYPE_MAP.update({
        "title": IntentTypeInfo(slide_type="bullets", require_image=False, sort_order=0, is_generatable=False),
        "problem": IntentTypeInfo(slide_type="bullets", require_image=True, sort_order=1, suggested_title="The Problem", requirements="Explain the problem", is_generatable=True),
        "thanks": IntentTypeInfo(slide_type="bullets", require_image=False, sort_order=99, is_generatable=False),
    })
    models.STATIC_SLIDES.clear()
    models.STATIC_SLIDES.update({
        "title": {"intent": "title", "title": "Test Title", "subtitle": "Sub", "speaker": "Speaker", "job_title": "Eng", "company": "Co", "company_url": "https://co.com", "event": "Event"},
        "thanks": {"intent": "thanks", "title": "Thanks", "bullets": ["Bye"], "speaker_notes": "Done"},
    })
    models.SECTION_DIVIDERS_CACHE.clear()
    models.SECTION_DIVIDERS_CACHE.extend([
        {"after_intent": "problem", "title": "Section 1", "subtitle": "", "image_filename": "div1.png", "sort_order": 1},
    ])
    models.THEMES_CACHE.clear()
    models.THEMES_CACHE.update({
        "dark": {"name": "dark", "display_name": "Dark Pro", "css_overrides": "", "is_active": True},
        "postgres": {"name": "postgres", "display_name": "PG Brand", "css_overrides": ":root { --x: 1; }", "is_active": True},
    })

    renderer_mod._initialized = True
    yield

    models.INTENT_TYPE_MAP.clear()
    models.INTENT_TYPE_MAP.update(old_itm)
    models.STATIC_SLIDES.clear()
    models.STATIC_SLIDES.update(old_ss)
    models.SECTION_DIVIDERS_CACHE.clear()
    models.SECTION_DIVIDERS_CACHE.extend(old_sd)
    models.THEMES_CACHE.clear()
    models.THEMES_CACHE.update(old_tc)


class TestCheckInitialized:

    def test_raises_when_not_initialized(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            _check_initialized()

    def test_passes_when_initialized(self, mock_loaders):
        _check_initialized()  # Should not raise


class TestGetIntentOrder:

    def test_returns_sorted_intents(self, mock_loaders):
        result = get_intent_order()
        assert result == ["title", "problem", "thanks"]

    def test_raises_without_init(self):
        with pytest.raises(RuntimeError):
            get_intent_order()


class TestGetTargetSlides:

    def test_counts_generatable_only(self, mock_loaders):
        result = get_target_slides()
        assert result == 1  # Only "problem" is generatable


class TestGetTitleSlide:

    def test_returns_title_data(self, mock_loaders):
        result = get_title_slide()
        assert result["title"] == "Test Title"
        assert result["speaker"] == "Speaker"


class TestGetThanksSlide:

    def test_returns_thanks_data(self, mock_loaders):
        result = get_thanks_slide()
        assert result["title"] == "Thanks"
        assert result["bullets"] == ["Bye"]


class TestGetSectionDividers:

    def test_returns_tuples(self, mock_loaders):
        result = get_section_dividers()
        assert result == [("problem", "Section 1")]


class TestGetDividerImages:

    def test_returns_title_to_filename_mapping(self, mock_loaders):
        result = get_divider_images()
        assert result == {"Section 1": "div1.png"}


class TestGetThemes:

    def test_returns_remapped_format(self, mock_loaders):
        result = get_themes()
        assert "dark" in result
        assert result["dark"]["name"] == "Dark Pro"
        assert result["dark"]["overrides"] == ""
        assert result["postgres"]["overrides"] == ":root { --x: 1; }"
