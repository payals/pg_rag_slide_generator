"""Unit tests for fragment composition engine (src/renderer.py).

Tests compose_slide_type_body() and DB-fragment regression equivalence.
"""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, DictLoader, ChoiceLoader

from src.renderer import compose_slide_type_body, _derive_fragment_order

TEMPLATE_DIR = str(Path(__file__).parent.parent.parent / "templates")


class TestComposeSlideTypeBody:

    def _make_fragments(self, **overrides):
        """Build a complete fragment dict with simple placeholder content."""
        base = {
            "statement": '<p>{{ slide.content_data.statement }}</p>',
            "split": '<div class="split">split content</div>',
            "flow": '<div class="flow">flow content</div>',
            "code": '<pre>code content</pre>',
            "diagram": '<div>diagram content</div>',
            "bullets": '<ul>{% for b in slide.bullets %}<li>{{ b }}</li>{% endfor %}</ul>',
        }
        base.update(overrides)
        return base

    def test_returns_string_with_all_types(self):
        result = compose_slide_type_body(self._make_fragments())
        assert result is not None
        assert isinstance(result, str)

    def test_contains_if_elif_chain(self):
        result = compose_slide_type_body(self._make_fragments())
        assert "{% if slide.slide_type == 'statement'" in result
        assert "{% elif slide.slide_type == 'split'" in result
        assert "{% elif slide.slide_type == 'flow'" in result
        assert "{% elif slide.slide_type == 'code'" in result
        assert "{% elif slide.slide_type == 'diagram'" in result
        assert "{% else %}" in result
        assert "{% endif %}" in result

    def test_bullets_is_else_fallback(self):
        result = compose_slide_type_body(self._make_fragments())
        else_pos = result.index("{% else %}")
        bullets_pos = result.index("slide.bullets")
        assert bullets_pos > else_pos

    def test_includes_image_block(self):
        result = compose_slide_type_body(self._make_fragments())
        assert "slide.image_path" in result
        assert "slide-image" in result

    def test_returns_none_if_empty(self):
        assert compose_slide_type_body({}) is None

    def test_returns_none_if_missing_type(self):
        frags = self._make_fragments()
        del frags["flow"]
        assert compose_slide_type_body(frags) is None

    def test_returns_none_if_none_value(self):
        frags = self._make_fragments()
        frags["code"] = None
        assert compose_slide_type_body(frags) is None

    def test_returns_none_if_bullets_missing(self):
        frags = self._make_fragments()
        del frags["bullets"]
        assert compose_slide_type_body(frags) is None

    def test_fragment_order_matches_constant(self):
        assert _derive_fragment_order() == ["code", "diagram", "flow", "split", "statement"]

    def test_statement_appears_first(self):
        result = compose_slide_type_body(self._make_fragments())
        first_if = result.index("{% if ")
        assert "'statement'" in result[first_if:first_if + 80]

    def test_composed_template_renders_with_jinja2(self):
        """Verify the composed string is valid Jinja2."""
        result = compose_slide_type_body(self._make_fragments())
        env = Environment(autoescape=True)
        template = env.from_string(result)
        assert template is not None


def _load_file_fragments() -> dict[str, str]:
    """Read all fragment files from templates/fragments/."""
    fragments = {}
    for stype in ["statement", "split", "flow", "code", "diagram", "bullets"]:
        frag_path = Path(TEMPLATE_DIR) / "fragments" / f"{stype}.html"
        fragments[stype] = frag_path.read_text().strip()
    return fragments


class TestFragmentCompositionRegression:
    """Verify DB-composed template is equivalent to the file-based template."""

    def _render_slide_type(self, env, slide_type, content_data):
        template = env.from_string(
            '{% include "_slide_type_body.html" %}'
        )
        slide = {
            "slide_type": slide_type,
            "content_data": content_data,
            "bullets": ["Fallback bullet 1", "Fallback bullet 2"],
            "image_path": None,
            "image_alt": None,
        }
        return template.render(slide=slide).strip()

    def test_all_types_render_identically(self):
        """Each slide type renders the same with DB fragments vs filesystem."""
        fragments = _load_file_fragments()
        composed = compose_slide_type_body(fragments)
        assert composed is not None

        file_env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True
        )
        db_env = Environment(
            loader=ChoiceLoader([
                DictLoader({"_slide_type_body.html": composed}),
                FileSystemLoader(TEMPLATE_DIR),
            ]),
            autoescape=True,
        )

        test_cases = {
            "statement": {"statement": "Bold claim", "subtitle": "With context"},
            "split": {
                "left_title": "Left", "right_title": "Right",
                "left_items": ["L1", "L2"], "right_items": ["R1", "R2"],
            },
            "flow": {
                "steps": [
                    {"label": "Step 1", "caption": "First"},
                    {"label": "Step 2", "caption": "Second"},
                ]
            },
            "code": {
                "code_block": "SELECT 1;", "language": "sql",
                "explain_bullets": ["Runs a query"],
            },
            "diagram": {
                "callouts": ["Point A", "Point B"], "caption": "Architecture diagram",
            },
            "bullets": None,
        }

        for stype, cd in test_cases.items():
            file_html = self._render_slide_type(file_env, stype, cd)
            db_html = self._render_slide_type(db_env, stype, cd)
            assert file_html == db_html, (
                f"Rendering mismatch for {stype}:\n"
                f"FILE:\n{file_html}\n\nDB:\n{db_html}"
            )


class TestDBFragmentRendering:
    """End-to-end regression: each slide type renders correctly with DB fragments."""

    @pytest.fixture
    def jinja_env_with_db_fragments(self):
        """Build a Jinja2 env using composed DB fragments (from files)."""
        fragments = _load_file_fragments()
        composed = compose_slide_type_body(fragments)
        return Environment(
            loader=ChoiceLoader([
                DictLoader({"_slide_type_body.html": composed}),
                FileSystemLoader(TEMPLATE_DIR),
            ]),
            autoescape=True,
        )

    def _render_fragment(self, env, slide_dict):
        template = env.get_template("slide_fragment.html")
        return template.render(slides=[slide_dict]).strip()

    def test_statement_renders(self, jinja_env_with_db_fragments):
        html = self._render_fragment(jinja_env_with_db_fragments, {
            "slide_type": "statement", "title": "Test", "is_title": False,
            "is_divider": False, "is_thanks": False,
            "content_data": {"statement": "Bold claim", "subtitle": "Sub"},
            "bullets": [], "speaker_notes": "", "image_path": None, "image_alt": None,
        })
        assert "statement-text" in html
        assert "Bold claim" in html
        assert "statement-subtitle" in html

    def test_split_renders(self, jinja_env_with_db_fragments):
        html = self._render_fragment(jinja_env_with_db_fragments, {
            "slide_type": "split", "title": "Test", "is_title": False,
            "is_divider": False, "is_thanks": False,
            "content_data": {
                "left_title": "Left", "right_title": "Right",
                "left_items": ["L1"], "right_items": ["R1"],
            },
            "bullets": [], "speaker_notes": "", "image_path": None, "image_alt": None,
        })
        assert "split-layout" in html
        assert "Left" in html
        assert "Right" in html

    def test_flow_renders(self, jinja_env_with_db_fragments):
        html = self._render_fragment(jinja_env_with_db_fragments, {
            "slide_type": "flow", "title": "Test", "is_title": False,
            "is_divider": False, "is_thanks": False,
            "content_data": {
                "steps": [{"label": "Step 1", "caption": "First"}, {"label": "Step 2", "caption": "Second"}],
            },
            "bullets": [], "speaker_notes": "", "image_path": None, "image_alt": None,
        })
        assert "flow-pipeline" in html
        assert "Step 1" in html
        assert "flow-arrow" in html

    def test_code_renders(self, jinja_env_with_db_fragments):
        html = self._render_fragment(jinja_env_with_db_fragments, {
            "slide_type": "code", "title": "Test", "is_title": False,
            "is_divider": False, "is_thanks": False,
            "content_data": {
                "code_block": "SELECT 1;", "language": "sql",
                "explain_bullets": ["Runs a query"],
            },
            "bullets": [], "speaker_notes": "", "image_path": None, "image_alt": None,
        })
        assert "code-block" in html
        assert "SELECT 1;" in html
        assert 'data-language="sql"' in html
        assert "code-explain" in html

    def test_diagram_renders(self, jinja_env_with_db_fragments):
        html = self._render_fragment(jinja_env_with_db_fragments, {
            "slide_type": "diagram", "title": "Test", "is_title": False,
            "is_divider": False, "is_thanks": False,
            "content_data": {
                "callouts": ["Point A"], "caption": "Architecture",
            },
            "bullets": [], "speaker_notes": "", "image_path": None, "image_alt": None,
        })
        assert "diagram-content" in html
        assert "Point A" in html
        assert "diagram-caption" in html

    def test_diagram_empty_callouts_no_wrapper(self, jinja_env_with_db_fragments):
        """Empty callouts + no caption should omit <div class="diagram-content">."""
        html = self._render_fragment(jinja_env_with_db_fragments, {
            "slide_type": "diagram", "title": "Test", "is_title": False,
            "is_divider": False, "is_thanks": False,
            "content_data": {"callouts": [], "caption": ""},
            "bullets": [], "speaker_notes": "",
            "image_path": "/images/gate.svg", "image_alt": "Gate chain",
        })
        assert "diagram-content" not in html
        assert "slide-image" in html
        assert "/images/gate.svg" in html

    def test_bullets_fallback_renders(self, jinja_env_with_db_fragments):
        html = self._render_fragment(jinja_env_with_db_fragments, {
            "slide_type": "bullets", "title": "Test", "is_title": False,
            "is_divider": False, "is_thanks": False,
            "content_data": None,
            "bullets": ["Bullet 1", "Bullet 2"],
            "speaker_notes": "", "image_path": None, "image_alt": None,
        })
        assert "Bullet 1" in html
        assert "Bullet 2" in html
        assert "<li>" in html

    def test_unknown_type_falls_back_to_bullets(self, jinja_env_with_db_fragments):
        html = self._render_fragment(jinja_env_with_db_fragments, {
            "slide_type": "unknown", "title": "Test", "is_title": False,
            "is_divider": False, "is_thanks": False,
            "content_data": None,
            "bullets": ["Fallback bullet"],
            "speaker_notes": "", "image_path": None, "image_alt": None,
        })
        assert "Fallback bullet" in html

    def test_image_block_renders(self, jinja_env_with_db_fragments):
        html = self._render_fragment(jinja_env_with_db_fragments, {
            "slide_type": "statement", "title": "Test", "is_title": False,
            "is_divider": False, "is_thanks": False,
            "content_data": {"statement": "Claim"},
            "bullets": [], "speaker_notes": "",
            "image_path": "/images/test.png", "image_alt": "Test image",
        })
        assert "slide-image" in html
        assert "/images/test.png" in html
