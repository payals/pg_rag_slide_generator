"""Unit tests for walk_content_data() in src/content_utils.py.

Covers scalar, list, and nested field traversal, plus edge cases
for missing/empty/None values and non-string list items.
"""

import pytest

from src.content_utils import walk_content_data, CONTENT_FIELD_MAP


def _upper(text: str) -> str:
    """Test transform: uppercase."""
    return text.upper()


class TestWalkContentDataScalars:

    def test_transforms_statement(self):
        cd = {"statement": "hello"}
        walk_content_data(cd, _upper)
        assert cd["statement"] == "HELLO"

    def test_transforms_subtitle(self):
        cd = {"subtitle": "sub"}
        walk_content_data(cd, _upper)
        assert cd["subtitle"] == "SUB"

    def test_transforms_caption(self):
        cd = {"caption": "cap"}
        walk_content_data(cd, _upper)
        assert cd["caption"] == "CAP"

    def test_transforms_code_block(self):
        cd = {"code_block": "select 1;"}
        walk_content_data(cd, _upper)
        assert cd["code_block"] == "SELECT 1;"

    def test_skips_missing_scalar(self):
        cd = {"statement": "hello"}
        walk_content_data(cd, _upper)
        assert "subtitle" not in cd

    def test_skips_non_string_scalar(self):
        cd = {"statement": 42}
        walk_content_data(cd, _upper)
        assert cd["statement"] == 42


class TestWalkContentDataLists:

    def test_transforms_list_items(self):
        cd = {"callouts": ["a", "b"]}
        walk_content_data(cd, _upper)
        assert cd["callouts"] == ["A", "B"]

    def test_transforms_explain_bullets(self):
        cd = {"explain_bullets": ["x", "y"]}
        walk_content_data(cd, _upper)
        assert cd["explain_bullets"] == ["X", "Y"]

    def test_transforms_left_items(self):
        cd = {"left_items": ["l1"], "right_items": ["r1"]}
        walk_content_data(cd, _upper)
        assert cd["left_items"] == ["L1"]
        assert cd["right_items"] == ["R1"]

    def test_transforms_bullets_in_content_data(self):
        cd = {"bullets": ["b1", "b2"]}
        walk_content_data(cd, _upper)
        assert cd["bullets"] == ["B1", "B2"]

    def test_skips_non_string_list_items(self):
        cd = {"callouts": ["text", 42, None]}
        walk_content_data(cd, _upper)
        assert cd["callouts"] == ["TEXT", 42, None]

    def test_empty_list_unchanged(self):
        cd = {"callouts": []}
        walk_content_data(cd, _upper)
        assert cd["callouts"] == []

    def test_missing_list_key_no_error(self):
        cd = {"statement": "hello"}
        walk_content_data(cd, _upper)
        assert "callouts" not in cd


class TestWalkContentDataNested:

    def test_transforms_step_label_and_caption(self):
        cd = {"steps": [
            {"label": "ingest", "caption": "load docs"},
            {"label": "embed", "caption": "compute vectors"},
        ]}
        walk_content_data(cd, _upper)
        assert cd["steps"][0]["label"] == "INGEST"
        assert cd["steps"][0]["caption"] == "LOAD DOCS"
        assert cd["steps"][1]["label"] == "EMBED"
        assert cd["steps"][1]["caption"] == "COMPUTE VECTORS"

    def test_step_missing_caption(self):
        cd = {"steps": [{"label": "only label"}]}
        walk_content_data(cd, _upper)
        assert cd["steps"][0]["label"] == "ONLY LABEL"
        assert "caption" not in cd["steps"][0]

    def test_step_non_dict_item_skipped(self):
        cd = {"steps": [{"label": "ok"}, "not a dict", None]}
        walk_content_data(cd, _upper)
        assert cd["steps"][0]["label"] == "OK"
        assert cd["steps"][1] == "not a dict"
        assert cd["steps"][2] is None

    def test_empty_steps_list(self):
        cd = {"steps": []}
        walk_content_data(cd, _upper)
        assert cd["steps"] == []

    def test_missing_steps_key_no_error(self):
        cd = {"callouts": ["a"]}
        walk_content_data(cd, _upper)
        assert "steps" not in cd


class TestWalkContentDataEdgeCases:

    def test_none_returns_none(self):
        assert walk_content_data(None, _upper) is None

    def test_empty_dict_returns_empty(self):
        cd = {}
        result = walk_content_data(cd, _upper)
        assert result == {}

    def test_returns_same_reference(self):
        cd = {"statement": "hello"}
        result = walk_content_data(cd, _upper)
        assert result is cd

    def test_custom_field_map(self):
        cd = {"custom_field": "hello", "statement": "world"}
        custom = {"scalar": ["custom_field"], "list": [], "nested": {}}
        walk_content_data(cd, _upper, fields=custom)
        assert cd["custom_field"] == "HELLO"
        assert cd["statement"] == "world"  # not in custom map

    def test_all_field_types_combined(self):
        cd = {
            "statement": "stmt",
            "caption": "cap",
            "callouts": ["c1", "c2"],
            "explain_bullets": ["e1"],
            "steps": [{"label": "s1", "caption": "sc1"}],
        }
        walk_content_data(cd, _upper)
        assert cd["statement"] == "STMT"
        assert cd["caption"] == "CAP"
        assert cd["callouts"] == ["C1", "C2"]
        assert cd["explain_bullets"] == ["E1"]
        assert cd["steps"][0]["label"] == "S1"
        assert cd["steps"][0]["caption"] == "SC1"


class TestBuildGlobalFieldMap:

    def test_merges_scalar_fields(self):
        from src.content_utils import build_global_field_map
        configs = {
            "statement": {"content_fields": {"scalar": ["statement", "subtitle"], "list": [], "nested": {}}},
            "code": {"content_fields": {"scalar": ["code_block", "language"], "list": [], "nested": {}}},
        }
        result = build_global_field_map(configs)
        assert set(result["scalar"]) == {"statement", "subtitle", "code_block", "language"}

    def test_merges_list_fields(self):
        from src.content_utils import build_global_field_map
        configs = {
            "split": {"content_fields": {"scalar": [], "list": ["left_items", "right_items"], "nested": {}}},
            "diagram": {"content_fields": {"scalar": [], "list": ["callouts"], "nested": {}}},
        }
        result = build_global_field_map(configs)
        assert set(result["list"]) == {"left_items", "right_items", "callouts"}

    def test_merges_nested_fields(self):
        from src.content_utils import build_global_field_map
        configs = {
            "flow": {"content_fields": {"scalar": [], "list": [], "nested": {"steps": ["label", "caption"]}}},
            "other": {"content_fields": {"scalar": [], "list": [], "nested": {}}},
        }
        result = build_global_field_map(configs)
        assert "steps" in result["nested"]
        assert set(result["nested"]["steps"]) == {"label", "caption"}

    def test_empty_input(self):
        from src.content_utils import build_global_field_map
        result = build_global_field_map({})
        assert result == {"scalar": [], "list": [], "nested": {}}

    def test_deduplicates(self):
        from src.content_utils import build_global_field_map
        configs = {
            "a": {"content_fields": {"scalar": ["caption"], "list": [], "nested": {}}},
            "b": {"content_fields": {"scalar": ["caption"], "list": [], "nested": {}}},
        }
        result = build_global_field_map(configs)
        assert result["scalar"].count("caption") == 1

    def test_sorted_output(self):
        from src.content_utils import build_global_field_map
        configs = {
            "a": {"content_fields": {"scalar": ["z_field", "a_field"], "list": [], "nested": {}}},
        }
        result = build_global_field_map(configs)
        assert result["scalar"] == ["a_field", "z_field"]


class TestInitContentFieldMap:

    def test_replaces_global_map(self):
        from src.content_utils import init_content_field_map
        import src.content_utils as mod
        original = mod.CONTENT_FIELD_MAP.copy()
        configs = {
            "test": {"content_fields": {"scalar": ["test_field"], "list": [], "nested": {}}},
        }
        init_content_field_map(configs)
        assert "test_field" in mod.CONTENT_FIELD_MAP["scalar"]
        mod.CONTENT_FIELD_MAP = original

    def test_noop_on_empty_input(self):
        from src.content_utils import init_content_field_map
        import src.content_utils as mod
        original = mod.CONTENT_FIELD_MAP.copy()
        init_content_field_map({})
        assert mod.CONTENT_FIELD_MAP == original


class TestContentFieldMapCompleteness:
    """Verify CONTENT_FIELD_MAP matches the fields used by existing functions."""

    def test_scalar_fields_match_llm_clean_slide_text(self):
        expected = {"statement", "subtitle", "caption", "code_block"}
        assert set(CONTENT_FIELD_MAP["scalar"]) == expected

    def test_list_fields_match_llm_clean_slide_text(self):
        expected = {"bullets", "left_items", "right_items", "explain_bullets", "callouts"}
        assert set(CONTENT_FIELD_MAP["list"]) == expected

    def test_nested_fields_match_llm_clean_slide_text(self):
        assert CONTENT_FIELD_MAP["nested"] == {"steps": ["label", "caption"]}
