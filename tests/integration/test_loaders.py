"""Integration tests for DB loader functions.

These tests hit the real database (via init_pool) and verify that
loader functions return correct data after migration 010.
"""

import pytest
import pytest_asyncio

import src.db as _db_mod
import src.models as _models_mod
from src.db import init_pool, close_pool
from src.models import (
    IntentTypeInfo,
    get_slide_type,
    load_intent_type_map,
    load_static_slides,
    load_section_dividers,
    load_themes,
    load_slide_type_configs,
    load_prompt_templates,
    should_select_image,
)


@pytest_asyncio.fixture(autouse=True)
async def db_pool():
    """Initialize and tear down DB pool once per test."""
    _db_mod._pool = None
    await init_pool()
    yield
    await close_pool()


class TestLoadIntentTypeMap:

    async def test_returns_17_intents(self):
        result = await load_intent_type_map()
        assert len(result) == 17

    async def test_all_intents_have_sort_order(self):
        result = await load_intent_type_map()
        for intent, info in result.items():
            assert isinstance(info.sort_order, int), f"{intent} missing sort_order"

    async def test_sort_order_unique(self):
        result = await load_intent_type_map()
        orders = [info.sort_order for info in result.values()]
        assert len(orders) == len(set(orders)), "Duplicate sort_order values"

    async def test_suggested_title_populated_for_generatable(self):
        result = await load_intent_type_map()
        for intent, info in result.items():
            if info.is_generatable:
                assert info.suggested_title, f"{intent} missing suggested_title"

    async def test_requirements_populated_for_generatable(self):
        result = await load_intent_type_map()
        for intent, info in result.items():
            if info.is_generatable:
                assert info.requirements, f"{intent} missing requirements"

    async def test_title_and_thanks_not_generatable(self):
        result = await load_intent_type_map()
        assert not result["title"].is_generatable
        assert not result["thanks"].is_generatable

    async def test_related_intents_populated(self):
        result = await load_intent_type_map()
        assert result["rag-in-postgres"].related_intents == ["what-is-rag"]
        assert result["mcp-tools"].related_intents == ["what-is-mcp"]
        assert result["observability"].related_intents == ["gates"]
        assert result["what-we-built"].related_intents == ["architecture"]
        assert result["takeaways"].related_intents == ["thesis"]

    async def test_intents_without_related_have_empty_list(self):
        result = await load_intent_type_map()
        assert result["problem"].related_intents == []

    async def test_global_cache_populated(self):
        await load_intent_type_map()
        assert len(_models_mod.INTENT_TYPE_MAP) == 17

    async def test_existing_helpers_still_work(self):
        await load_intent_type_map()
        assert get_slide_type("thesis") == "statement"
        assert get_slide_type("problem") == "bullets"
        assert should_select_image("problem") is True
        assert should_select_image("thesis") is False


class TestLoadStaticSlides:

    async def test_returns_two_slides(self):
        result = await load_static_slides()
        assert len(result) == 2

    async def test_has_title_and_thanks(self):
        result = await load_static_slides()
        assert "title" in result
        assert "thanks" in result

    async def test_title_slide_fields(self):
        result = await load_static_slides()
        title = result["title"]
        assert title["title"] == "Postgres as AI Control Plane"
        assert title["subtitle"] == "Building RAG + MCP Workflows Inside the Database"
        assert title["speaker"] == "Payal Singh"
        assert title["job_title"] == "Senior Database Reliability Engineer"
        assert title["company"] == "NetApp"
        assert title["event"] == "Scale23x \u2022 March 2026"

    async def test_thanks_slide_fields(self):
        result = await load_static_slides()
        thanks = result["thanks"]
        assert thanks["title"] == "Thank You & Questions"
        assert isinstance(thanks["bullets"], list)
        assert len(thanks["bullets"]) == 4
        assert "GitHub" in thanks["bullets"][0]

    async def test_global_cache_populated(self):
        await load_static_slides()
        assert len(_models_mod.STATIC_SLIDES) == 2


class TestLoadSectionDividers:

    async def test_returns_five_dividers(self):
        result = await load_section_dividers()
        assert len(result) == 5

    async def test_sorted_by_sort_order(self):
        result = await load_section_dividers()
        orders = [d["sort_order"] for d in result]
        assert orders == sorted(orders)

    async def test_first_divider_is_why_postgres(self):
        result = await load_section_dividers()
        assert result[0]["after_intent"] == "problem"
        assert result[0]["title"] == "Why Postgres?"
        assert result[0]["image_filename"] == "divider_01_why_postgres.png"

    async def test_all_dividers_have_required_fields(self):
        result = await load_section_dividers()
        for d in result:
            assert d["after_intent"], "Missing after_intent"
            assert d["title"], "Missing title"
            assert isinstance(d["sort_order"], int)

    async def test_global_cache_populated(self):
        await load_section_dividers()
        assert len(_models_mod.SECTION_DIVIDERS_CACHE) == 5


class TestLoadThemes:

    async def test_returns_at_least_two_themes(self):
        result = await load_themes()
        assert len(result) >= 2

    async def test_has_dark_and_postgres(self):
        result = await load_themes()
        assert "dark" in result
        assert "postgres" in result

    async def test_dark_theme_fields(self):
        result = await load_themes()
        dark = result["dark"]
        assert dark["display_name"] == "Dark Professional"
        assert dark["css_overrides"] == ""
        assert dark["is_active"] is True

    async def test_postgres_theme_has_css_overrides(self):
        result = await load_themes()
        pg = result["postgres"]
        assert "--accent-color: #336791" in pg["css_overrides"]

    async def test_global_cache_populated(self):
        await load_themes()
        assert len(_models_mod.THEMES_CACHE) >= 2


class TestLoadSlideTypeConfigs:

    async def test_returns_6_types(self):
        result = await load_slide_type_configs()
        assert len(result) == 6

    async def test_all_slide_types_present(self):
        result = await load_slide_type_configs()
        expected = {"statement", "split", "flow", "code", "diagram", "bullets"}
        assert set(result.keys()) == expected

    async def test_each_has_prompt_schema(self):
        result = await load_slide_type_configs()
        for stype, config in result.items():
            assert config["prompt_schema"], f"{stype} missing prompt_schema"
            assert "Return valid JSON" in config["prompt_schema"], \
                f"{stype} prompt_schema doesn't contain expected header"

    async def test_each_has_content_fields(self):
        result = await load_slide_type_configs()
        for stype, config in result.items():
            cf = config["content_fields"]
            assert "scalar" in cf, f"{stype} missing scalar in content_fields"
            assert "list" in cf, f"{stype} missing list in content_fields"
            assert "nested" in cf, f"{stype} missing nested in content_fields"

    async def test_flow_has_nested_steps(self):
        result = await load_slide_type_configs()
        flow_cf = result["flow"]["content_fields"]
        assert "steps" in flow_cf["nested"]
        assert "label" in flow_cf["nested"]["steps"]
        assert "caption" in flow_cf["nested"]["steps"]

    async def test_global_cache_populated(self):
        await load_slide_type_configs()
        from src.models import SLIDE_TYPE_CONFIGS
        assert len(SLIDE_TYPE_CONFIGS) == 6


class TestLoadPromptTemplates:

    async def test_returns_5_purposes(self):
        result = await load_prompt_templates()
        assert len(result) == 5

    async def test_all_purposes_present(self):
        result = await load_prompt_templates()
        expected = {
            "slide_generation", "rewrite_format", "rewrite_grounding",
            "rewrite_novelty", "alternative_queries",
        }
        assert set(result.keys()) == expected

    async def test_each_has_system_and_user_prompt(self):
        result = await load_prompt_templates()
        for purpose, tmpl in result.items():
            assert tmpl["system_prompt"], f"{purpose} missing system_prompt"
            assert tmpl["user_prompt"], f"{purpose} missing user_prompt"

    async def test_slide_generation_has_format_placeholders(self):
        result = await load_prompt_templates()
        sys_prompt = result["slide_generation"]["system_prompt"]
        user_prompt = result["slide_generation"]["user_prompt"]
        assert "{retrieved_chunks}" in sys_prompt or "retrieved_chunks" in sys_prompt
        assert "{intent}" in user_prompt

    async def test_global_cache_populated(self):
        await load_prompt_templates()
        from src.models import PROMPT_TEMPLATES
        assert len(PROMPT_TEMPLATES) == 5


class TestFragmentFileParity:
    """Verify fragment files match slide_type_config.html_fragment in DB."""

    async def test_all_fragments_match_files(self):
        from pathlib import Path
        configs = await load_slide_type_configs()
        fragments_dir = Path(__file__).parent.parent.parent / "templates" / "fragments"

        for stype in ["statement", "split", "flow", "code", "diagram", "bullets"]:
            config = configs.get(stype)
            assert config is not None, f"No config for {stype}"
            db_frag = (config.get("html_fragment") or "").strip()
            file_frag = (fragments_dir / f"{stype}.html").read_text().strip()
            assert db_frag == file_frag, (
                f"Fragment mismatch for {stype}: "
                f"DB={len(db_frag)} chars, file={len(file_frag)} chars"
            )

    async def test_no_null_fragments(self):
        configs = await load_slide_type_configs()
        for stype, config in configs.items():
            assert config.get("html_fragment") is not None, (
                f"html_fragment is NULL for {stype}"
            )


class TestContentFieldMapIntegration:

    async def test_merged_field_map_covers_all_types(self):
        from src.content_utils import build_global_field_map
        configs = await load_slide_type_configs()
        merged = build_global_field_map(configs)

        assert "statement" in merged["scalar"]
        assert "subtitle" in merged["scalar"]
        assert "caption" in merged["scalar"]
        assert "code_block" in merged["scalar"]
        assert "language" in merged["scalar"]
        assert "left_title" in merged["scalar"]
        assert "right_title" in merged["scalar"]

        assert "bullets" in merged["list"]
        assert "left_items" in merged["list"]
        assert "right_items" in merged["list"]
        assert "explain_bullets" in merged["list"]
        assert "callouts" in merged["list"]

        assert "steps" in merged["nested"]
        assert "label" in merged["nested"]["steps"]
        assert "caption" in merged["nested"]["steps"]
