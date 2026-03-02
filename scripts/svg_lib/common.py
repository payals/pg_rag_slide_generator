"""
Common palette, primitives, and canvas helpers for SVG generation.

Canvas: 1600x900px (16:9 presentation ratio)
"""

from dataclasses import dataclass
from typing import Optional
import html


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
    """Centralized color palette for all generated images."""

    # Backgrounds
    BG_DARK = "#0a0e27"
    BG_CARD = "#111836"
    BG_CODE = "#0d1117"

    # Primary
    BLUE = "#2563eb"
    TEAL = "#0d9488"
    INDIGO = "#6366f1"

    # Accent
    GREEN = "#22c55e"
    ORANGE = "#f97316"
    RED = "#ef4444"
    PURPLE = "#8b5cf6"
    YELLOW = "#eab308"
    CYAN = "#06b6d4"
    PINK = "#ec4899"

    # Text
    TEXT_LIGHT = "#f1f5f9"
    TEXT_MUTED = "#94a3b8"
    TEXT_DIM = "#64748b"

    # Borders / lines
    BORDER = "#1e293b"
    BORDER_LIGHT = "#334155"
    GRID = "#1a1f3d"

    # Gradients (start, end)
    GRAD_BLUE = ("#2563eb", "#1d4ed8")
    GRAD_TEAL = ("#0d9488", "#0f766e")
    GRAD_PURPLE = ("#8b5cf6", "#7c3aed")
    GRAD_GREEN = ("#22c55e", "#16a34a")
    GRAD_ORANGE = ("#f97316", "#ea580c")
    GRAD_RED = ("#ef4444", "#dc2626")

    # Semantic
    PASS = "#22c55e"
    FAIL = "#ef4444"
    WARN = "#f97316"
    INFO = "#2563eb"

    # PostgreSQL brand
    PG_BLUE = "#336791"
    PG_DARK = "#1a3a5c"


# ---------------------------------------------------------------------------
# Canvas constants
# ---------------------------------------------------------------------------

WIDTH = 1600
HEIGHT = 900
FONT_FAMILY = "Arial, 'Segoe UI', Helvetica, sans-serif"
CORNER_RADIUS = 12
CARD_RADIUS = 8


# ---------------------------------------------------------------------------
# XML / SVG helpers
# ---------------------------------------------------------------------------

def escape_xml(text: str) -> str:
    """Escape text for safe XML embedding."""
    return html.escape(str(text), quote=True)


def svg_doc(body: str, *, width: int = WIDTH, height: int = HEIGHT,
            bg: str = Palette.BG_DARK) -> str:
    """Wrap SVG body in a complete SVG document with background."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{width}" height="{height}"
     viewBox="0 0 {width} {height}">
  <defs>
    <style>
      text {{ font-family: {FONT_FAMILY}; }}
    </style>
  </defs>
  <rect width="{width}" height="{height}" fill="{bg}" rx="0"/>
  {body}
</svg>"""


# ---------------------------------------------------------------------------
# Shape primitives
# ---------------------------------------------------------------------------

def rounded_rect(x: float, y: float, w: float, h: float,
                 fill: str, stroke: str = "none", stroke_width: float = 0,
                 rx: float = CORNER_RADIUS, opacity: float = 1.0,
                 extra: str = "") -> str:
    """Rounded rectangle."""
    s = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke != "none" else ""
    o = f' opacity="{opacity}"' if opacity < 1.0 else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
            f'rx="{rx}" fill="{fill}"{s}{o} {extra}/>')


def circle(cx: float, cy: float, r: float, fill: str,
           stroke: str = "none", stroke_width: float = 0,
           opacity: float = 1.0) -> str:
    """Circle."""
    s = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke != "none" else ""
    o = f' opacity="{opacity}"' if opacity < 1.0 else ""
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"{s}{o}/>'


def ellipse(cx: float, cy: float, rx: float, ry: float, fill: str,
            stroke: str = "none", stroke_width: float = 0,
            opacity: float = 1.0) -> str:
    """Ellipse."""
    s = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke != "none" else ""
    o = f' opacity="{opacity}"' if opacity < 1.0 else ""
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}"{s}{o}/>'


def line(x1: float, y1: float, x2: float, y2: float,
         stroke: str, stroke_width: float = 2,
         dash: Optional[str] = None, opacity: float = 1.0) -> str:
    """Line segment."""
    d = f' stroke-dasharray="{dash}"' if dash else ""
    o = f' opacity="{opacity}"' if opacity < 1.0 else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"{d}{o}/>')


def polyline(points: list[tuple[float, float]], stroke: str,
             fill: str = "none", stroke_width: float = 2) -> str:
    """Polyline from list of (x, y) tuples."""
    pts = " ".join(f"{x},{y}" for x, y in points)
    return (f'<polyline points="{pts}" stroke="{stroke}" '
            f'fill="{fill}" stroke-width="{stroke_width}"/>')


def polygon(points: list[tuple[float, float]], fill: str,
            stroke: str = "none", stroke_width: float = 0,
            opacity: float = 1.0) -> str:
    """Polygon from list of (x, y) tuples."""
    pts = " ".join(f"{x},{y}" for x, y in points)
    s = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke != "none" else ""
    o = f' opacity="{opacity}"' if opacity < 1.0 else ""
    return f'<polygon points="{pts}" fill="{fill}"{s}{o}/>'


def path(d: str, fill: str = "none", stroke: str = "none",
         stroke_width: float = 2, opacity: float = 1.0) -> str:
    """SVG path element."""
    f_attr = f' fill="{fill}"'
    s_attr = f' stroke="{stroke}" stroke-width="{stroke_width}"' if stroke != "none" else ""
    o = f' opacity="{opacity}"' if opacity < 1.0 else ""
    return f'<path d="{d}"{f_attr}{s_attr}{o}/>'


def text(x: float, y: float, content: str, *,
         font_size: float = 34, fill: str = Palette.TEXT_LIGHT,
         anchor: str = "middle", weight: str = "normal",
         dominant_baseline: str = "middle",
         font_family: Optional[str] = None,
         opacity: float = 1.0,
         max_width: Optional[float] = None) -> str:
    """Text element."""
    ff = f' font-family="{font_family}"' if font_family else ""
    o = f' opacity="{opacity}"' if opacity < 1.0 else ""
    mw = f' textLength="{max_width}" lengthAdjust="spacingAndGlyphs"' if max_width else ""
    return (f'<text x="{x}" y="{y}" font-size="{font_size}" '
            f'fill="{fill}" text-anchor="{anchor}" '
            f'dominant-baseline="{dominant_baseline}" '
            f'font-weight="{weight}"{ff}{o}{mw}>'
            f'{escape_xml(content)}</text>')


def text_multiline(x: float, y: float, lines: list[str], *,
                   font_size: float = 30, fill: str = Palette.TEXT_LIGHT,
                   anchor: str = "middle", weight: str = "normal",
                   line_height: float = 1.4) -> str:
    """Multi-line text using tspan elements."""
    dy = font_size * line_height
    parts = []
    for i, ln in enumerate(lines):
        tspan_y = y + i * dy
        parts.append(
            f'<text x="{x}" y="{tspan_y}" font-size="{font_size}" '
            f'fill="{fill}" text-anchor="{anchor}" '
            f'dominant-baseline="{(("middle"))}" '
            f'font-weight="{weight}">{escape_xml(ln)}</text>'
        )
    return "\n".join(parts)


def group(content: str, *, transform: str = "", opacity: float = 1.0) -> str:
    """SVG group wrapper."""
    t = f' transform="{transform}"' if transform else ""
    o = f' opacity="{opacity}"' if opacity < 1.0 else ""
    return f"<g{t}{o}>\n{content}\n</g>"


# ---------------------------------------------------------------------------
# Arrows & connectors
# ---------------------------------------------------------------------------

def arrow_right(x1: float, y: float, x2: float,
                stroke: str = Palette.TEXT_MUTED,
                stroke_width: float = 2,
                head_size: float = 8) -> str:
    """Horizontal arrow from left to right."""
    parts = [
        line(x1, y, x2, y, stroke, stroke_width),
        polygon(
            [(x2, y), (x2 - head_size, y - head_size / 2), (x2 - head_size, y + head_size / 2)],
            fill=stroke,
        ),
    ]
    return "\n".join(parts)


def arrow_down(x: float, y1: float, y2: float,
               stroke: str = Palette.TEXT_MUTED,
               stroke_width: float = 2,
               head_size: float = 8) -> str:
    """Vertical arrow from top to bottom."""
    parts = [
        line(x, y1, x, y2, stroke, stroke_width),
        polygon(
            [(x, y2), (x - head_size / 2, y2 - head_size), (x + head_size / 2, y2 - head_size)],
            fill=stroke,
        ),
    ]
    return "\n".join(parts)


def arrow_between(x1: float, y1: float, x2: float, y2: float,
                  stroke: str = Palette.TEXT_MUTED,
                  stroke_width: float = 2,
                  head_size: float = 8) -> str:
    """Arrow between two arbitrary points."""
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    sin_a = math.sin(angle)
    cos_a = math.cos(angle)

    # Arrow head points
    hx1 = x2 - head_size * cos_a + (head_size / 2) * sin_a
    hy1 = y2 - head_size * sin_a - (head_size / 2) * cos_a
    hx2 = x2 - head_size * cos_a - (head_size / 2) * sin_a
    hy2 = y2 - head_size * sin_a + (head_size / 2) * cos_a

    parts = [
        line(x1, y1, x2, y2, stroke, stroke_width),
        polygon([(x2, y2), (hx1, hy1), (hx2, hy2)], fill=stroke),
    ]
    return "\n".join(parts)


def curved_arrow(x1: float, y1: float, x2: float, y2: float,
                 stroke: str = Palette.TEXT_MUTED,
                 stroke_width: float = 2,
                 curve: float = 30) -> str:
    """Curved arrow using a quadratic bezier."""
    mx = (x1 + x2) / 2
    my = min(y1, y2) - curve
    d = f"M {x1},{y1} Q {mx},{my} {x2},{y2}"
    return path(d, stroke=stroke, stroke_width=stroke_width)


# ---------------------------------------------------------------------------
# Gradient definitions
# ---------------------------------------------------------------------------

def linear_gradient(grad_id: str, color1: str, color2: str,
                    x1: str = "0%", y1: str = "0%",
                    x2: str = "0%", y2: str = "100%") -> str:
    """Linear gradient definition."""
    return (f'<linearGradient id="{grad_id}" x1="{x1}" y1="{y1}" '
            f'x2="{x2}" y2="{y2}">\n'
            f'  <stop offset="0%" stop-color="{color1}"/>\n'
            f'  <stop offset="100%" stop-color="{color2}"/>\n'
            f'</linearGradient>')


def radial_gradient(grad_id: str, inner: str, outer: str,
                    cx: str = "50%", cy: str = "50%",
                    r: str = "50%") -> str:
    """Radial gradient definition."""
    return (f'<radialGradient id="{grad_id}" cx="{cx}" cy="{cy}" r="{r}">\n'
            f'  <stop offset="0%" stop-color="{inner}"/>\n'
            f'  <stop offset="100%" stop-color="{outer}"/>\n'
            f'</radialGradient>')


# ---------------------------------------------------------------------------
# Compound elements
# ---------------------------------------------------------------------------

def labeled_box(x: float, y: float, w: float, h: float,
                label: str, fill: str = Palette.BG_CARD,
                border_color: str = Palette.BLUE,
                text_color: str = Palette.TEXT_LIGHT,
                font_size: float = 30,
                rx: float = CORNER_RADIUS,
                sublabel: Optional[str] = None,
                sublabel_color: str = Palette.TEXT_MUTED) -> str:
    """Box with centered label text and optional sublabel."""
    parts = [
        rounded_rect(x, y, w, h, fill, stroke=border_color, stroke_width=2, rx=rx),
        text(x + w / 2, y + h / 2 - (8 if sublabel else 0),
             label, font_size=font_size, fill=text_color, weight="600"),
    ]
    if sublabel:
        parts.append(
            text(x + w / 2, y + h / 2 + 14, sublabel,
                 font_size=font_size - 2, fill=sublabel_color)
        )
    return "\n".join(parts)


def icon_badge(cx: float, cy: float, icon_char: str,
               bg_color: str = Palette.BLUE, size: float = 28) -> str:
    """Circular badge with a text/emoji icon."""
    return "\n".join([
        circle(cx, cy, size / 2, bg_color),
        text(cx, cy, icon_char, font_size=size * 0.5, fill=Palette.TEXT_LIGHT),
    ])


def status_dot(x: float, y: float, passed: bool, size: float = 8) -> str:
    """Green/red status indicator dot."""
    color = Palette.PASS if passed else Palette.FAIL
    return circle(x, y, size, color)


def card(x: float, y: float, w: float, h: float,
         title: str, body_lines: list[str],
         accent_color: str = Palette.BLUE,
         bg: str = Palette.BG_CARD) -> str:
    """Card component with accent top border. Fonts scale with card height."""
    # Scale font sizes proportionally to card height (baseline: h=160)
    scale = max(h / 160, 1.0)
    title_fs = min(30 * scale, 44)
    body_fs = min(24 * scale, 36)
    line_gap = min(30 * scale, 48)

    # Vertically center the text block within the card
    n_body = len(body_lines)
    text_block_h = title_fs + (n_body * line_gap if n_body else 0)
    top_pad = max((h - text_block_h) / 2, 20)

    title_y = y + top_pad
    parts = [
        rounded_rect(x, y, w, h, bg, stroke=Palette.BORDER, stroke_width=1, rx=CARD_RADIUS),
        # Accent bar at top
        f'<rect x="{x}" y="{y}" width="{w}" height="4" rx="{CARD_RADIUS}" fill="{accent_color}"/>',
        text(x + w / 2, title_y, title, font_size=title_fs, fill=Palette.TEXT_LIGHT, weight="700"),
    ]
    for i, ln in enumerate(body_lines):
        parts.append(
            text(x + w / 2, title_y + title_fs + 8 + i * line_gap, ln,
                 font_size=body_fs, fill=Palette.TEXT_MUTED)
        )
    return "\n".join(parts)


def cylinder(x: float, y: float, w: float, h: float,
             fill: str, label: str = "",
             stroke: str = "none", stroke_width: float = 0) -> str:
    """Database cylinder shape."""
    ry = min(h * 0.12, 20)  # ellipse height for the cap
    body_h = h - ry

    parts = []
    # Body
    parts.append(f'<rect x="{x}" y="{y + ry}" width="{w}" height="{body_h}" fill="{fill}"/>')
    # Bottom ellipse
    parts.append(f'<ellipse cx="{x + w / 2}" cy="{y + h}" rx="{w / 2}" ry="{ry}" fill="{fill}"/>')
    # Top ellipse (lighter)
    parts.append(f'<ellipse cx="{x + w / 2}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" fill="{fill}"/>')
    # Top ellipse highlight
    parts.append(f'<ellipse cx="{x + w / 2}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" '
                 f'fill="white" opacity="0.1"/>')
    if stroke != "none":
        parts.append(f'<ellipse cx="{x + w / 2}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" '
                     f'fill="none" stroke="{stroke}" stroke-width="{stroke_width}"/>')

    if label:
        parts.append(text(x + w / 2, y + h / 2 + ry / 2, label,
                          font_size=24, fill=Palette.TEXT_LIGHT, weight="600"))
    return "\n".join(parts)
