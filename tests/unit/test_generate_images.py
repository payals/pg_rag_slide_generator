"""
Tests for the image generation pipeline.

Tests cover:
- SVG template rendering (each category produces valid SVG)
- Image definitions completeness
- Generate script logic (dry run, pattern matching, skip existing)
- Mermaid placeholder generation
- Purge logic for image re-ingestion
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# Add project root for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.svg_lib.common import (
    Palette, WIDTH, HEIGHT, svg_doc, escape_xml, rounded_rect, circle, text,
    arrow_right, arrow_down, labeled_box, card, cylinder, linear_gradient,
)
from scripts.svg_lib.diagrams import render_diagram, DIAGRAM_TEMPLATES
from scripts.svg_lib.charts import render_chart, CHART_TEMPLATES
from scripts.svg_lib.code_blocks import render_code_block, CODE_TEMPLATES
from scripts.svg_lib.decorative import render_decorative, DECORATIVE_TEMPLATES
from scripts.svg_lib.image_defs import IMAGE_DEFS, get_svg_image_names, get_image_def, DIAGRAM, CHART, CODE, DECORATIVE
from scripts.generate_images import (
    generate_svg_image, generate_all, EXISTING_IMAGES, MERMAID_IMAGES,
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

class TestPalette:
    """Test palette constants."""

    def test_bg_dark_is_hex(self):
        assert Palette.BG_DARK.startswith("#")
        assert len(Palette.BG_DARK) == 7

    def test_all_colors_are_hex(self):
        for attr in dir(Palette):
            if attr.startswith("_") or attr.startswith("GRAD"):
                continue
            val = getattr(Palette, attr)
            if isinstance(val, str):
                assert val.startswith("#"), f"{attr} = {val} is not a hex color"


class TestSVGHelpers:
    """Test SVG primitive functions."""

    def test_svg_doc_has_required_elements(self):
        doc = svg_doc("<circle/>")
        assert '<?xml version="1.0"' in doc
        assert '<svg xmlns="http://www.w3.org/2000/svg"' in doc
        assert f'width="{WIDTH}"' in doc
        assert f'height="{HEIGHT}"' in doc
        assert "<circle/>" in doc

    def test_escape_xml(self):
        assert escape_xml("<script>") == "&lt;script&gt;"
        assert escape_xml('"test"') == "&quot;test&quot;"
        assert escape_xml("hello") == "hello"

    def test_rounded_rect(self):
        rect = rounded_rect(10, 20, 100, 50, "#ff0000")
        assert 'x="10"' in rect
        assert 'y="20"' in rect
        assert 'width="100"' in rect
        assert 'fill="#ff0000"' in rect

    def test_circle(self):
        c = circle(100, 200, 30, "#00ff00")
        assert 'cx="100"' in c
        assert 'cy="200"' in c
        assert 'r="30"' in c

    def test_text(self):
        t = text(50, 100, "Hello World", font_size=16, fill="#fff")
        assert "Hello World" in t
        assert 'x="50"' in t
        assert 'font-size="16"' in t

    def test_text_escapes_xml(self):
        t = text(0, 0, "<script>alert('xss')</script>")
        assert "<script>" not in t
        assert "&lt;script&gt;" in t

    def test_arrow_right(self):
        a = arrow_right(0, 100, 200)
        assert "<line" in a
        assert "<polygon" in a

    def test_labeled_box(self):
        b = labeled_box(10, 20, 100, 50, "Test Label")
        assert "Test Label" in b
        assert "<rect" in b

    def test_cylinder(self):
        c = cylinder(100, 100, 80, 120, "#336791", "DB")
        assert "DB" in c
        assert "<ellipse" in c


class TestLinearGradient:
    def test_gradient_has_stops(self):
        g = linear_gradient("grad1", "#ff0000", "#0000ff")
        assert 'id="grad1"' in g
        assert "#ff0000" in g
        assert "#0000ff" in g


# ---------------------------------------------------------------------------
# Diagram templates
# ---------------------------------------------------------------------------

class TestDiagramTemplates:
    """Test all diagram template functions produce valid SVG."""

    @pytest.mark.parametrize("template", list(DIAGRAM_TEMPLATES.keys()))
    def test_template_produces_svg(self, template):
        # Minimal config
        configs = {
            "box_and_arrow": {"components": [{"label": "A"}, {"label": "B"}]},
            "layered_boxes": {"layers": [{"label": "L1"}, {"label": "L2"}]},
            "split_comparison": {"left": {"title": "Left", "items": ["a"]},
                                 "right": {"title": "Right", "items": ["b"]}},
            "concentric_rings": {"rings": [{"label": "Inner"}, {"label": "Outer"}]},
            "card_grid": {"cards": [{"title": "C1", "body": ["line"]}]},
            "layer_stack": {"layers": [{"label": "Base"}, {"label": "Top"}]},
            "merge_flow": {"inputs": [{"label": "I1"}], "merger": "M", "output": "O"},
            "hub_spoke_horizontal": {"hub": {"label": "Hub"},
                                     "left": [{"label": "L"}],
                                     "right": [{"label": "R"}]},
            "two_col_mapping": {"left": [{"label": "A"}], "right": [{"label": "B"}]},
            "horizontal_flow": {"steps": [{"label": "S1"}, {"label": "S2"}]},
            "nested_rects": {"labels": ["Outer", "Inner"]},
        }
        cfg = configs.get(template, {})
        result = render_diagram(template, cfg)
        assert result.startswith("<?xml")
        assert "<svg" in result
        assert "</svg>" in result

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError, match="Unknown diagram template"):
            render_diagram("nonexistent", {})


# ---------------------------------------------------------------------------
# Chart templates
# ---------------------------------------------------------------------------

class TestChartTemplates:
    @pytest.mark.parametrize("template", list(CHART_TEMPLATES.keys()))
    def test_template_produces_svg(self, template):
        configs = {
            "venn_3": {"circles": [{"label": "A"}, {"label": "B"}, {"label": "C"}]},
            "matrix_grid": {"cols": ["C1"], "rows": ["R1"], "data": [[True]]},
            "pyramid": {"levels": [{"label": "Top"}, {"label": "Bottom"}]},
            "mind_map": {"center": "Hub", "branches": [{"label": "B1", "children": ["c"]}]},
            "checklist": {"items": ["Item 1", "Item 2"]},
            "stat_cards": {"stats": [{"value": "42", "label": "Things"}]},
        }
        cfg = configs.get(template, {})
        result = render_chart(template, cfg)
        assert result.startswith("<?xml")
        assert "</svg>" in result

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError, match="Unknown chart template"):
            render_chart("nonexistent", {})


# ---------------------------------------------------------------------------
# Code block templates
# ---------------------------------------------------------------------------

class TestCodeBlockTemplates:
    @pytest.mark.parametrize("template", list(CODE_TEMPLATES.keys()))
    def test_template_produces_svg(self, template):
        configs = {
            "code_editor": {"code": ["SELECT 1;"], "filename": "test.sql"},
            "code_editor_split": {"left_code": ["a"], "right_code": ["b"]},
            "db_table": {"columns": ["col1"], "rows": [["val1"]]},
            "multi_panel": {"panels": [{"title": "P1", "content": ["line"]}]},
        }
        cfg = configs.get(template, {})
        result = render_code_block(template, cfg)
        assert result.startswith("<?xml")
        assert "</svg>" in result

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError, match="Unknown code template"):
            render_code_block("nonexistent", {})


# ---------------------------------------------------------------------------
# Decorative templates
# ---------------------------------------------------------------------------

class TestDecorativeTemplates:
    @pytest.mark.parametrize("template", list(DECORATIVE_TEMPLATES.keys()))
    def test_template_produces_svg(self, template):
        configs = {
            "gradient_elephant_spotlight": {"title": "Test"},
            "blueprint_circuit": {"title": "Test"},
            "layered_waves": {"title": "Test"},
            "dashboard_shapes": {"title": "Test"},
            "geometric_stage": {"title": "Test"},
            "toolbox": {"tools": ["Tool1"]},
            "magnifying_glass": {"title": "Test"},
            "castle_fortress": {"layers": [{"label": "L1"}]},
            "air_traffic_tower": {"title": "Test"},
            "factory_assembly": {"stations": [{"label": "S1"}]},
            "student_analogy": {"title": "Test"},
            "bouncer_metaphor": {"title": "Test"},
            "recursive_frames": {"depth": 3},
        }
        cfg = configs.get(template, {})
        result = render_decorative(template, cfg)
        assert result.startswith("<?xml")
        assert "</svg>" in result

    def test_unknown_template_raises(self):
        with pytest.raises(ValueError, match="Unknown decorative template"):
            render_decorative("nonexistent", {})


# ---------------------------------------------------------------------------
# Image definitions
# ---------------------------------------------------------------------------

class TestImageDefs:
    """Test image definitions are complete and valid."""

    def test_all_defs_have_required_keys(self):
        for name, defn in IMAGE_DEFS.items():
            assert "category" in defn, f"{name} missing 'category'"
            assert "template" in defn, f"{name} missing 'template'"
            assert "config" in defn, f"{name} missing 'config'"

    def test_all_categories_are_valid(self):
        valid = {DIAGRAM, CHART, CODE, DECORATIVE}
        for name, defn in IMAGE_DEFS.items():
            assert defn["category"] in valid, f"{name} has invalid category: {defn['category']}"

    def test_all_templates_exist(self):
        all_templates = {}
        all_templates.update({(DIAGRAM, k): True for k in DIAGRAM_TEMPLATES})
        all_templates.update({(CHART, k): True for k in CHART_TEMPLATES})
        all_templates.update({(CODE, k): True for k in CODE_TEMPLATES})
        all_templates.update({(DECORATIVE, k): True for k in DECORATIVE_TEMPLATES})

        for name, defn in IMAGE_DEFS.items():
            key = (defn["category"], defn["template"])
            assert key in all_templates, (
                f"{name}: template '{defn['template']}' not found in "
                f"category '{defn['category']}'"
            )

    def test_image_count(self):
        assert len(IMAGE_DEFS) == 45, f"Expected 45 SVG defs, got {len(IMAGE_DEFS)}"

    def test_get_svg_image_names(self):
        names = get_svg_image_names()
        assert len(names) == 45
        assert "architecture_01_system_diagram" in names

    def test_get_image_def(self):
        defn = get_image_def("architecture_01_system_diagram")
        assert defn["category"] == DIAGRAM

    def test_get_image_def_unknown_raises(self):
        with pytest.raises(KeyError):
            get_image_def("nonexistent")

    def test_no_overlap_with_existing(self):
        """SVG image defs should not include manually created images."""
        for name in IMAGE_DEFS:
            assert name not in EXISTING_IMAGES, (
                f"{name} is in both IMAGE_DEFS and EXISTING_IMAGES"
            )


# ---------------------------------------------------------------------------
# End-to-end SVG generation
# ---------------------------------------------------------------------------

class TestSVGGeneration:
    """Test that every image definition renders without errors."""

    @pytest.mark.parametrize("name", list(IMAGE_DEFS.keys()))
    def test_each_image_renders(self, name):
        """Each image def should render to valid SVG without exceptions."""
        defn = IMAGE_DEFS[name]
        category = defn["category"]
        template = defn["template"]
        config = defn["config"]

        renderers = {
            DIAGRAM: render_diagram,
            CHART: render_chart,
            CODE: render_code_block,
            DECORATIVE: render_decorative,
        }

        renderer = renderers[category]
        result = renderer(template, config)

        assert result.startswith("<?xml"), f"{name} did not produce valid SVG"
        assert "</svg>" in result, f"{name} SVG is not closed"
        assert len(result) > 500, f"{name} SVG seems too short ({len(result)} bytes)"


# ---------------------------------------------------------------------------
# Generate script logic
# ---------------------------------------------------------------------------

class TestGenerateScript:
    def test_generate_svg_to_temp_dir(self):
        """Test generating a single SVG to a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            defn = IMAGE_DEFS["divider_01_why_postgres"]
            result = generate_svg_image("divider_01_why_postgres", defn, output_dir)

            assert result is not None
            assert result.exists()
            assert result.suffix == ".svg"
            content = result.read_text()
            assert "<?xml" in content

    def test_generate_skips_existing(self):
        """Test that existing files are skipped when force=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            # Pre-create the file
            (output_dir / "divider_01_why_postgres.svg").write_text("existing")

            defn = IMAGE_DEFS["divider_01_why_postgres"]
            result = generate_svg_image("divider_01_why_postgres", defn, output_dir, force=False)
            assert result is None  # Should be skipped

    def test_generate_overwrites_with_force(self):
        """Test that force=True overwrites existing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            (output_dir / "divider_01_why_postgres.svg").write_text("old")

            defn = IMAGE_DEFS["divider_01_why_postgres"]
            result = generate_svg_image("divider_01_why_postgres", defn, output_dir, force=True)
            assert result is not None
            content = result.read_text()
            assert "<?xml" in content  # Should be new SVG, not "old"

    def test_dry_run_generates_nothing(self):
        """Test dry run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            report = generate_all(dry_run=True)
            # Nothing should be generated
            assert report["svg_generated"] == 0
            assert report["mermaid_generated"] == 0

    def test_name_pattern_filters(self):
        """Test that name pattern filtering works."""
        report = generate_all(name_pattern="gates_*", dry_run=True)
        details = report["details"]
        for d in details:
            assert d["name"].startswith("gates_")

    def test_mermaid_images_set(self):
        """Test Mermaid images set matches .mmd files."""
        mermaid_dir = PROJECT_ROOT / "scripts" / "mermaid_defs"
        mmd_files = {p.stem for p in mermaid_dir.glob("*.mmd")}
        assert MERMAID_IMAGES == mmd_files, (
            f"Mismatch: MERMAID_IMAGES has {MERMAID_IMAGES - mmd_files} extra, "
            f"missing {mmd_files - MERMAID_IMAGES}"
        )

    def test_existing_images_count(self):
        assert len(EXISTING_IMAGES) == 16


# ---------------------------------------------------------------------------
# Canvas size constants
# ---------------------------------------------------------------------------

class TestCanvasConstants:
    """Verify canvas constants match the enlarged 1600x900 spec."""

    def test_width(self):
        assert WIDTH == 1600, f"Expected WIDTH=1600, got {WIDTH}"

    def test_height(self):
        assert HEIGHT == 900, f"Expected HEIGHT=900, got {HEIGHT}"

    def test_svg_doc_uses_new_dimensions(self):
        doc = svg_doc("<rect/>")
        assert 'width="1600"' in doc
        assert 'height="900"' in doc

    def test_mermaid_dimensions(self):
        from scripts.generate_images import MERMAID_WIDTH, MERMAID_HEIGHT
        assert MERMAID_WIDTH == 1600
        assert MERMAID_HEIGHT == 900


# ---------------------------------------------------------------------------
# Purge logic
# ---------------------------------------------------------------------------

class TestPurgeLogic:
    """Test the --purge flag for image re-ingestion."""

    @pytest.mark.asyncio
    async def test_purge_deletes_image_docs(self):
        """Verify purge runs UPDATE then DELETE in correct FK-safe order."""
        from src.ingest_images import purge_image_data

        mock_conn = AsyncMock()
        # conn.execute returns status strings like "UPDATE 3", "DELETE 5"
        mock_conn.execute = AsyncMock(side_effect=["UPDATE 3", "DELETE 5"])

        result = await purge_image_data(mock_conn)

        assert result == 5
        assert mock_conn.execute.call_count == 2

        # Verify call order: UPDATE first, DELETE second
        calls = mock_conn.execute.call_args_list
        assert "UPDATE slide SET image_id = NULL" in calls[0][0][0]
        assert "DELETE FROM doc WHERE doc_type = 'image'" in calls[1][0][0]

    @pytest.mark.asyncio
    async def test_purge_flag_false_skips_delete(self):
        """Verify no delete when purge=False."""
        from src.ingest_images import ingest_images

        with patch("src.ingest_images.asyncpg") as mock_asyncpg, \
             patch("src.ingest_images.get_openai_client") as mock_client, \
             patch("src.ingest_images.find_images", return_value=[]), \
             patch("src.ingest_images.DATABASE_URL", "postgres://test"):

            mock_conn = AsyncMock()
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)

            report = await ingest_images(purge=False)

            # Should not call fetchval for purge queries
            mock_conn.fetchval.assert_not_called()
