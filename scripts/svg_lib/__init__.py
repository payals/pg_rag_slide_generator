"""SVG Template Engine for Scale23x presentation images."""

from scripts.svg_lib.common import Palette, svg_doc, escape_xml
from scripts.svg_lib.diagrams import render_diagram
from scripts.svg_lib.charts import render_chart
from scripts.svg_lib.code_blocks import render_code_block
from scripts.svg_lib.decorative import render_decorative

__all__ = [
    "Palette",
    "svg_doc",
    "escape_xml",
    "render_diagram",
    "render_chart",
    "render_code_block",
    "render_decorative",
]
