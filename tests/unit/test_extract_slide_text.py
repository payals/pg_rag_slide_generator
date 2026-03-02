"""
Unit tests for extract_slide_text() utility function.

Covers all 6 slide types + edge cases (missing content_data, empty fields).
"""

import pytest

from src.models import extract_slide_text


class TestExtractSlideTextBullets:
    """Default bullet type."""

    def test_returns_bullets(self):
        draft = {"slide_type": "bullets", "bullets": ["A", "B", "C"]}
        assert extract_slide_text(draft) == ["A", "B", "C"]

    def test_no_slide_type_defaults_to_bullets(self):
        draft = {"bullets": ["X", "Y"]}
        assert extract_slide_text(draft) == ["X", "Y"]

    def test_empty_bullets(self):
        draft = {"slide_type": "bullets", "bullets": []}
        assert extract_slide_text(draft) == []

    def test_missing_bullets_key(self):
        draft = {"slide_type": "bullets"}
        assert extract_slide_text(draft) == []


class TestExtractSlideTextStatement:

    def test_returns_statement_and_subtitle(self):
        draft = {
            "slide_type": "statement",
            "content_data": {"statement": "Big idea", "subtitle": "Supporting line"},
        }
        assert extract_slide_text(draft) == ["Big idea", "Supporting line"]

    def test_statement_only(self):
        draft = {
            "slide_type": "statement",
            "content_data": {"statement": "Only this"},
        }
        assert extract_slide_text(draft) == ["Only this"]

    def test_empty_content_data(self):
        draft = {"slide_type": "statement", "content_data": {}}
        assert extract_slide_text(draft) == []

    def test_none_content_data(self):
        draft = {"slide_type": "statement"}
        assert extract_slide_text(draft) == []


class TestExtractSlideTextSplit:

    def test_merges_left_and_right_with_titles(self):
        draft = {
            "slide_type": "split",
            "title": "Postgres vs Vector DBs",
            "content_data": {
                "left_title": "Postgres",
                "right_title": "Dedicated",
                "left_items": ["L1", "L2"],
                "right_items": ["R1"],
            },
        }
        assert extract_slide_text(draft) == [
            "Postgres vs Vector DBs \u2013 Postgres: L1",
            "Postgres vs Vector DBs \u2013 Postgres: L2",
            "Postgres vs Vector DBs \u2013 Dedicated: R1",
        ]

    def test_missing_column_titles(self):
        draft = {
            "slide_type": "split",
            "title": "Compare",
            "content_data": {"left_items": ["A"], "right_items": ["B"]},
        }
        assert extract_slide_text(draft) == [
            "Compare \u2013 : A",
            "Compare \u2013 : B",
        ]

    def test_empty_items(self):
        draft = {"slide_type": "split", "content_data": {}}
        assert extract_slide_text(draft) == []


class TestExtractSlideTextFlow:

    def test_joins_label_and_caption_with_title_prefix(self):
        draft = {
            "slide_type": "flow",
            "title": "Gate Pipeline",
            "content_data": {
                "steps": [
                    {"label": "G1", "caption": "Retrieve"},
                    {"label": "G2", "caption": "Cite"},
                ]
            },
        }
        result = extract_slide_text(draft)
        assert result == ["Gate Pipeline: G1 – Retrieve", "Gate Pipeline: G2 – Cite"]

    def test_label_only_with_title(self):
        draft = {
            "slide_type": "flow",
            "title": "Steps",
            "content_data": {"steps": [{"label": "Step1"}]},
        }
        assert extract_slide_text(draft) == ["Steps: Step1 –"]

    def test_no_title_still_works(self):
        draft = {
            "slide_type": "flow",
            "content_data": {"steps": [{"label": "G1", "caption": "Retrieve"}]},
        }
        result = extract_slide_text(draft)
        assert result == [": G1 – Retrieve"]


class TestExtractSlideTextCode:

    def test_returns_explain_and_code(self):
        draft = {
            "slide_type": "code",
            "content_data": {
                "explain_bullets": ["This does X"],
                "code_block": "SELECT 1;",
            },
        }
        assert extract_slide_text(draft) == ["This does X", "SELECT 1;"]

    def test_code_only(self):
        draft = {
            "slide_type": "code",
            "content_data": {"code_block": "SELECT 1;"},
        }
        assert extract_slide_text(draft) == ["SELECT 1;"]


class TestExtractSlideTextDiagram:

    def test_returns_callouts_prefixed_with_title(self):
        draft = {
            "slide_type": "diagram",
            "title": "System Architecture",
            "content_data": {"callouts": ["A", "B"], "caption": "Overview"},
        }
        assert extract_slide_text(draft) == [
            "System Architecture: A",
            "System Architecture: B",
            "Overview",
        ]

    def test_empty_caption_filtered(self):
        draft = {
            "slide_type": "diagram",
            "title": "Arch",
            "content_data": {"callouts": ["Only"], "caption": ""},
        }
        assert extract_slide_text(draft) == ["Arch: Only"]

    def test_no_title_still_works(self):
        draft = {
            "slide_type": "diagram",
            "content_data": {"callouts": ["X"], "caption": "Cap"},
        }
        assert extract_slide_text(draft) == [": X", "Cap"]


class TestExtractSlideTextFallback:
    """Fallback to bullets when type-specific content_data is empty."""

    def test_diagram_falls_back_to_bullets(self):
        draft = {
            "slide_type": "diagram",
            "content_data": {},
            "bullets": ["Fallback A", "Fallback B"],
        }
        assert extract_slide_text(draft) == ["Fallback A", "Fallback B"]

    def test_code_falls_back_to_bullets(self):
        draft = {
            "slide_type": "code",
            "content_data": {},
            "bullets": ["Some bullet"],
        }
        assert extract_slide_text(draft) == ["Some bullet"]

    def test_split_falls_back_to_bullets(self):
        draft = {
            "slide_type": "split",
            "content_data": {},
            "bullets": ["Left stuff", "Right stuff"],
        }
        assert extract_slide_text(draft) == ["Left stuff", "Right stuff"]

    def test_no_fallback_when_content_data_present(self):
        draft = {
            "slide_type": "diagram",
            "title": "Diagram",
            "content_data": {"callouts": ["Real callout"]},
            "bullets": ["Should not appear"],
        }
        assert extract_slide_text(draft) == ["Diagram: Real callout"]

    def test_no_fallback_when_no_bullets_either(self):
        draft = {"slide_type": "diagram", "content_data": {}}
        assert extract_slide_text(draft) == []
