"""
Abstract, geometric, and illustrated SVG templates.

Decorative images for section dividers, metaphors, and conceptual illustrations.
Uses gradients, patterns, and stylized shapes rather than photorealistic art.
"""

import math
from scripts.svg_lib.common import (
    Palette, WIDTH, HEIGHT, CORNER_RADIUS,
    svg_doc, escape_xml, rounded_rect, circle, ellipse,
    line, polygon, path, text, group,
    linear_gradient, radial_gradient,
)


# ---------------------------------------------------------------------------
# Elephant silhouette (simplified PostgreSQL mascot outline)
# ---------------------------------------------------------------------------

_ELEPHANT_PATH = (
    "M 0,-40 C -15,-50 -35,-45 -40,-30 C -45,-15 -40,5 -35,15 "
    "C -30,25 -25,35 -15,40 L -10,40 L -10,25 L -15,25 C -20,20 -22,10 -20,0 "
    "C -18,-10 -12,-18 -5,-20 C 2,-22 10,-18 15,-10 C 20,-2 22,8 20,18 "
    "L 15,25 L 15,40 L 20,40 C 30,35 35,25 38,15 C 41,5 42,-10 38,-25 "
    "C 34,-35 25,-45 15,-48 C 8,-50 0,-48 0,-40 Z"
)


def _elephant_silhouette(cx: float, cy: float, scale: float = 2.5,
                         fill: str = Palette.PG_BLUE, opacity: float = 1.0) -> str:
    """Render simplified elephant shape."""
    return (f'<g transform="translate({cx},{cy}) scale({scale})" opacity="{opacity}">'
            f'<path d="{_ELEPHANT_PATH}" fill="{fill}"/>'
            f'</g>')


# ---------------------------------------------------------------------------
# Decorative templates
# ---------------------------------------------------------------------------

def _gradient_elephant_spotlight(cfg: dict) -> str:
    """Gradient background + elephant silhouette with spotlight glow."""
    title = cfg.get("title", "")
    subtitle = cfg.get("subtitle", "")
    parts = []

    # Gradient defs
    parts.append(f'<defs>')
    parts.append(radial_gradient("spotlight", "#1a3a6d", Palette.BG_DARK,
                                 cx="50%", cy="45%", r="50%"))
    parts.append(radial_gradient("glow", "#2563eb33", "#00000000",
                                 cx="50%", cy="45%", r="40%"))
    parts.append(f'</defs>')

    # Background with radial spotlight
    parts.append(f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#spotlight)"/>')

    # Glow effect
    parts.append(f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#glow)"/>')

    # Elephant
    parts.append(_elephant_silhouette(WIDTH / 2, HEIGHT / 2 - 30, scale=3.5,
                                      fill=Palette.PG_BLUE, opacity=0.6))

    # Spotlight cone (subtle)
    parts.append(polygon(
        [(WIDTH / 2, 0), (WIDTH / 2 - 200, HEIGHT), (WIDTH / 2 + 200, HEIGHT)],
        fill="white", opacity=0.03
    ))

    if title:
        parts.append(text(WIDTH / 2, HEIGHT - 100, title,
                          font_size=54, weight="700", fill=Palette.TEXT_LIGHT))
    if subtitle:
        parts.append(text(WIDTH / 2, HEIGHT - 55, subtitle,
                          font_size=34, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts), bg=Palette.BG_DARK)


def _blueprint_circuit(cfg: dict) -> str:
    """Blueprint grid lines with circuit patterns on dark blue."""
    title = cfg.get("title", "")
    subtitle = cfg.get("subtitle", "")
    parts = []

    # Grid lines
    grid_color = "#162044"
    for x in range(0, WIDTH + 1, 40):
        parts.append(line(x, 0, x, HEIGHT, grid_color, 0.5))
    for y in range(0, HEIGHT + 1, 40):
        parts.append(line(0, y, WIDTH, y, grid_color, 0.5))

    # Circuit traces — scaled for 1600x900
    circuit_color = Palette.BLUE
    trace_opacity = 0.3
    traces = [
        [(267, 0), (267, 267), (533, 267), (533, 533), (800, 533)],
        [(1333, 0), (1333, 213), (1067, 213), (1067, 453), (800, 453)],
        [(0, 667), (400, 667), (400, 400), (667, 400)],
        [(WIDTH, 267), (1200, 267), (1200, 667), (933, 667)],
    ]

    for trace in traces:
        for i in range(len(trace) - 1):
            parts.append(line(trace[i][0], trace[i][1],
                              trace[i + 1][0], trace[i + 1][1],
                              circuit_color, 2, opacity=trace_opacity))
        # Nodes at corners
        for px, py in trace:
            parts.append(circle(px, py, 4, circuit_color, opacity=trace_opacity + 0.1))

    # Center highlight
    parts.append(circle(WIDTH / 2, HEIGHT / 2, 80, circuit_color, opacity=0.05))
    parts.append(circle(WIDTH / 2, HEIGHT / 2, 80, "none",
                        stroke=circuit_color, stroke_width=1, opacity=0.2))

    if title:
        parts.append(text(WIDTH / 2, HEIGHT / 2 - 15, title,
                          font_size=54, weight="700", fill=Palette.TEXT_LIGHT))
    if subtitle:
        parts.append(text(WIDTH / 2, HEIGHT / 2 + 35, subtitle,
                          font_size=34, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts))


def _layered_waves(cfg: dict) -> str:
    """Abstract layered waves with glowing particles."""
    title = cfg.get("title", "")
    subtitle = cfg.get("subtitle", "")
    parts = []

    # Waves (3 layers) - start higher, fill to bottom
    wave_colors = [Palette.BLUE, Palette.TEAL, Palette.PURPLE]
    for i, color in enumerate(wave_colors):
        y_base = 200 + i * 200
        amplitude = 40 + i * 20
        frequency = 0.008 + i * 0.002

        d = f"M 0,{y_base}"
        for x in range(0, WIDTH + 10, 5):
            y = y_base + amplitude * math.sin(x * frequency + i * 1.5)
            d += f" L {x},{y}"
        d += f" L {WIDTH},{HEIGHT} L 0,{HEIGHT} Z"
        parts.append(path(d, fill=color, opacity=0.15))

    # Glowing particles — scaled for 1600x900
    particles = [
        (200, 267, 3), (400, 200, 2), (667, 373, 4), (933, 160, 2.5),
        (1200, 333, 3), (1400, 240, 2), (267, 533, 2), (600, 467, 3),
        (867, 400, 2), (1133, 507, 3), (1333, 440, 2.5),
    ]
    for px, py, pr in particles:
        parts.append(circle(px, py, pr, Palette.CYAN, opacity=0.6))
        parts.append(circle(px, py, pr * 3, Palette.CYAN, opacity=0.1))

    if title:
        parts.append(text(WIDTH / 2, HEIGHT / 2 - 80, title,
                          font_size=54, weight="700", fill=Palette.TEXT_LIGHT))
    if subtitle:
        parts.append(text(WIDTH / 2, HEIGHT / 2 - 35, subtitle,
                          font_size=34, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts))


def _dashboard_shapes(cfg: dict) -> str:
    """Abstract monitor/dashboard shapes with data dots."""
    title = cfg.get("title", "")
    subtitle = cfg.get("subtitle", "")
    parts = []

    # Monitor outline — scaled for 1600x900
    mon_w, mon_h = 667, 400
    mon_x = WIDTH / 2 - mon_w / 2
    mon_y = HEIGHT / 2 - mon_h / 2 - 30

    parts.append(rounded_rect(mon_x, mon_y, mon_w, mon_h, Palette.BG_CARD,
                               stroke=Palette.BORDER_LIGHT, stroke_width=2, rx=12))

    # Monitor stand
    parts.append(f'<rect x="{WIDTH / 2 - 40}" y="{mon_y + mon_h}" width="80" height="30" fill="{Palette.BORDER}"/>')
    parts.append(f'<rect x="{WIDTH / 2 - 80}" y="{mon_y + mon_h + 30}" width="160" height="8" rx="4" fill="{Palette.BORDER}"/>')

    # Mini bar chart inside monitor
    bar_colors = [Palette.BLUE, Palette.TEAL, Palette.GREEN, Palette.PURPLE, Palette.ORANGE]
    bar_heights = [120, 180, 90, 210, 150]
    bar_w = 40
    bar_gap = 20
    bars_total = len(bar_heights) * bar_w + (len(bar_heights) - 1) * bar_gap
    bar_start_x = WIDTH / 2 - bars_total / 2
    bar_base_y = mon_y + mon_h - 30

    for i, bh in enumerate(bar_heights):
        bx = bar_start_x + i * (bar_w + bar_gap)
        by = bar_base_y - bh * 0.8
        parts.append(rounded_rect(bx, by, bar_w, bh * 0.8,
                                   bar_colors[i], rx=4, opacity=0.7))

    # Data dots around monitor
    import random
    random.seed(42)  # deterministic
    for _ in range(20):
        dx = random.randint(40, WIDTH - 40)
        dy = random.randint(40, HEIGHT - 40)
        # Skip dots that overlap with monitor
        if mon_x - 20 < dx < mon_x + mon_w + 20 and mon_y - 20 < dy < mon_y + mon_h + 60:
            continue
        parts.append(circle(dx, dy, random.randint(2, 4),
                            Palette.CYAN, opacity=random.uniform(0.2, 0.5)))

    if title:
        parts.append(text(WIDTH / 2, HEIGHT - 70, title,
                          font_size=48, weight="700", fill=Palette.TEXT_LIGHT))
    if subtitle:
        parts.append(text(WIDTH / 2, HEIGHT - 30, subtitle,
                          font_size=30, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts))


def _geometric_stage(cfg: dict) -> str:
    """Geometric stage/curtain with spotlight cone."""
    title = cfg.get("title", "")
    subtitle = cfg.get("subtitle", "")
    parts = []

    # Curtain sides — scaled for 1600x900
    curtain_w = 133
    for x in [0, WIDTH - curtain_w]:
        parts.append(f'<rect x="{x}" y="0" width="{curtain_w}" height="{HEIGHT}" '
                     f'fill="{Palette.RED}" opacity="0.15"/>')
        # Folds
        for fy in range(0, HEIGHT, 30):
            parts.append(line(x + curtain_w / 2, fy, x + curtain_w / 2, fy + 15,
                              Palette.RED, 1, opacity=0.1))

    # Stage floor
    parts.append(polygon(
        [(100, HEIGHT), (WIDTH - 100, HEIGHT), (WIDTH - 50, HEIGHT - 100), (50, HEIGHT - 100)],
        fill="#1a1a2e", opacity=0.8
    ))

    # Spotlight cone from top
    parts.append(polygon(
        [(WIDTH / 2, 0), (WIDTH / 2 - 250, HEIGHT - 100), (WIDTH / 2 + 250, HEIGHT - 100)],
        fill="white", opacity=0.04
    ))

    # Spotlight circle on stage
    parts.append(ellipse(WIDTH / 2, HEIGHT - 100, 200, 30, "white", opacity=0.05))
    parts.append(ellipse(WIDTH / 2, HEIGHT - 100, 120, 18, "white", opacity=0.08))

    if title:
        parts.append(text(WIDTH / 2, HEIGHT / 2 - 30, title,
                          font_size=56, weight="700", fill=Palette.TEXT_LIGHT))
    if subtitle:
        parts.append(text(WIDTH / 2, HEIGHT / 2 + 25, subtitle,
                          font_size=34, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts))


def _toolbox(cfg: dict) -> str:
    """Simplified SVG toolbox with tool icons."""
    tools = cfg.get("tools", [])
    title = cfg.get("title", "")
    parts = []

    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700"))

    # Toolbox body — full-width for projector readability
    box_w, box_h = 1400, HEIGHT - 100
    box_x = WIDTH / 2 - box_w / 2
    box_y = 65

    parts.append(rounded_rect(box_x, box_y, box_w, box_h,
                               Palette.BG_CARD, stroke=Palette.BLUE, stroke_width=2, rx=12))

    # Handle
    handle_w = 160
    parts.append(rounded_rect(WIDTH / 2 - handle_w / 2, box_y - 15, handle_w, 24,
                               Palette.BLUE, rx=8))

    # Divider
    parts.append(line(box_x + 20, box_y + 50, box_x + box_w - 20, box_y + 50,
                      Palette.BORDER_LIGHT, 1))

    # Tool icons in grid — larger circles and fonts for projector
    n = len(tools)
    cols = 3
    rows_count = (n + cols - 1) // cols
    icon_w = (box_w - 80) / cols
    icon_h = (box_h - 80) / max(rows_count, 1)
    icon_r = 55  # large icon circles

    tool_colors = [Palette.BLUE, Palette.GREEN, Palette.TEAL,
                   Palette.PURPLE, Palette.ORANGE, Palette.CYAN]

    for i, tool in enumerate(tools):
        col = i % cols
        row = i // cols
        ix = box_x + 40 + col * icon_w + icon_w / 2
        iy = box_y + 70 + row * icon_h + icon_h / 2

        color = tool_colors[i % len(tool_colors)]
        tool_label = tool.get("label", tool) if isinstance(tool, dict) else tool

        # Icon circle — large for projector visibility
        parts.append(circle(ix, iy - 20, icon_r, color, opacity=0.15))
        parts.append(circle(ix, iy - 20, icon_r, "none", stroke=color, stroke_width=3))
        # Gear/wrench icon (simplified)
        parts.append(text(ix, iy - 20, "⚙", font_size=52, fill=color))
        # Label
        parts.append(text(ix, iy + icon_r + 10, tool_label, font_size=36,
                          fill=Palette.TEXT_LIGHT, weight="600"))

    return svg_doc("\n".join(parts))


def _magnifying_glass(cfg: dict) -> str:
    """SVG magnifying glass over stylized data table."""
    title = cfg.get("title", "")
    parts = []

    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700"))

    # Data table background - fill canvas
    tbl_x, tbl_y = 80, 65
    tbl_w, tbl_h = WIDTH - 160, HEIGHT - 100
    parts.append(rounded_rect(tbl_x, tbl_y, tbl_w, tbl_h,
                               Palette.BG_CARD, stroke=Palette.BORDER, stroke_width=1, rx=8))

    # Table rows — scaled for 1600x900
    for i in range(12):
        ry = tbl_y + 20 + i * 48
        if i % 2 == 0:
            parts.append(f'<rect x="{tbl_x + 5}" y="{ry}" width="{tbl_w - 10}" height="42" '
                         f'fill="{Palette.BG_CODE}" rx="4"/>')
        # Fake data bars
        for j in range(5):
            bx = tbl_x + 20 + j * 240
            bw = 80 + (i * j * 17) % 130
            parts.append(rounded_rect(bx, ry + 10, bw, 20, Palette.BORDER, rx=3))

    # Magnifying glass — scaled for 1600x900
    glass_cx, glass_cy = 800, 427
    glass_r = 130
    # Lens
    parts.append(circle(glass_cx, glass_cy, glass_r, Palette.CYAN, opacity=0.08))
    parts.append(circle(glass_cx, glass_cy, glass_r, "none",
                        stroke=Palette.CYAN, stroke_width=3))
    # Handle
    handle_angle = math.radians(45)
    hx1 = glass_cx + glass_r * math.cos(handle_angle)
    hy1 = glass_cy + glass_r * math.sin(handle_angle)
    hx2 = hx1 + 80
    hy2 = hy1 + 80
    parts.append(line(hx1, hy1, hx2, hy2, Palette.BORDER_LIGHT, 8))
    parts.append(line(hx1, hy1, hx2, hy2, Palette.CYAN, 4, opacity=0.5))

    # Highlight inside lens
    parts.append(circle(glass_cx - 30, glass_cy - 30, 15, "white", opacity=0.1))

    return svg_doc("\n".join(parts))


def _castle_fortress(cfg: dict) -> str:
    """Geometric castle cross-section with labeled security layers — large fonts."""
    layers = cfg.get("layers", [])
    title = cfg.get("title", "")
    parts = []

    title_h = 75 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    # Castle structure — fill canvas
    cx = WIDTH / 2
    base_w = 1200
    base_y = HEIGHT - 50

    colors = [Palette.BLUE, Palette.TEAL, Palette.GREEN, Palette.PURPLE]

    # Concentric walls (from outside in)
    n = len(layers) if layers else 4
    wall_inset = 120  # px inset per layer
    outer_h = base_y - title_h - 30

    for i in range(n):
        inset = i * wall_inset
        w = base_w - inset * 2
        h = outer_h - inset * 1.2
        x = cx - w / 2
        y = base_y - h

        color = colors[i % len(colors)] if i < len(colors) else Palette.BORDER

        # Wall
        parts.append(rounded_rect(x, y, w, h, "none",
                                   stroke=color, stroke_width=3, rx=6))

        # Battlements at top
        batt_w = 24
        batt_h = 18
        for bx in range(int(x) + 12, int(x + w) - 12, 44):
            parts.append(f'<rect x="{bx}" y="{y - batt_h}" width="{batt_w}" '
                         f'height="{batt_h}" fill="{color}" opacity="0.4"/>')

        # Label — large, with background pill for readability
        label = layers[i].get("label", f"Layer {i + 1}") if i < len(layers) else ""
        if label:
            label_y = y + 32
            pill_w = max(len(label) * 18, 160)
            pill_h = 44
            parts.append(rounded_rect(cx - pill_w / 2, label_y - pill_h / 2,
                                       pill_w, pill_h, Palette.BG_DARK,
                                       stroke=color, stroke_width=1, rx=pill_h // 2,
                                       opacity=0.9))
            parts.append(text(cx, label_y, label, font_size=32, weight="700", fill=color))

    # Gate
    gate_w, gate_h = 80, 120
    gate_y = base_y - gate_h - 10
    parts.append(f'<rect x="{cx - gate_w / 2}" y="{gate_y}" width="{gate_w}" '
                 f'height="{gate_h}" rx="30" fill="{Palette.BG_DARK}" '
                 f'stroke="{Palette.BORDER_LIGHT}" stroke-width="2"/>')

    return svg_doc("\n".join(parts))


# ---------------------------------------------------------------------------
# Illustrated metaphors
# ---------------------------------------------------------------------------

def _air_traffic_tower(cfg: dict) -> str:
    """Geometric tower with radar circles and plane icons."""
    title = cfg.get("title", "")
    parts = []

    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700"))

    # Tower — scaled for 1600x900
    tower_x = WIDTH / 2 - 40
    tower_w = 80
    tower_h = 470
    tower_y = HEIGHT - tower_h - 50

    # Tower shaft
    parts.append(f'<rect x="{tower_x}" y="{tower_y + 80}" width="{tower_w}" '
                 f'height="{tower_h - 80}" fill="{Palette.PG_BLUE}" opacity="0.7"/>')
    # Tower cab
    parts.append(rounded_rect(tower_x - 40, tower_y, tower_w + 80, 80,
                               Palette.PG_BLUE, stroke=Palette.BLUE, stroke_width=2, rx=8))
    # Windows
    for wx in range(int(tower_x) - 25, int(tower_x) + tower_w + 30, 25):
        parts.append(f'<rect x="{wx}" y="{tower_y + 15}" width="15" height="25" '
                     f'rx="3" fill="{Palette.CYAN}" opacity="0.3"/>')

    # Label
    parts.append(text(WIDTH / 2, tower_y + 55, "PostgreSQL",
                      font_size=28, weight="700", fill=Palette.TEXT_LIGHT))

    # Radar circles
    radar_cx, radar_cy = WIDTH / 2, tower_y - 10
    for r in [60, 120, 180, 240]:
        parts.append(circle(radar_cx, radar_cy, r, "none",
                            stroke=Palette.GREEN, stroke_width=1, opacity=0.15))

    # Plane icons (simple triangles) — scaled for 1600x900
    planes = [(400, 200), (1067, 267), (267, 467), (1267, 533)]
    for px, py in planes:
        parts.append(polygon(
            [(px, py - 12), (px + 24, py), (px, py + 6), (px - 6, py)],
            fill=Palette.TEXT_MUTED, opacity=0.6
        ))
        parts.append(text(px + 30, py, "LLM", font_size=22, fill=Palette.TEXT_DIM, anchor="start"))

    # Ground
    parts.append(line(0, HEIGHT - 40, WIDTH, HEIGHT - 40, Palette.BORDER_LIGHT, 1))

    return svg_doc("\n".join(parts))


def _factory_assembly(cfg: dict) -> str:
    """Conveyor line with PG-branded QC stations, descriptions, and slide items."""
    stations = cfg.get("stations", [])
    title = cfg.get("title", "")
    parts = []

    title_h = 70 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 40, title, font_size=52, weight="700"))

    # Gate descriptions for each station
    gate_details = {
        "G1: Retrieval": ["Hybrid search", "pgvector + pg_trgm",
                          "RRF ranking", "Top-K chunks",
                          "fn_hybrid_search()"],
        "G2: Citations": ["Every claim cited", "chunk_id traceable",
                          "Source verified", "Trust level check",
                          "fn_validate_cite()"],
        "G3: Format": ["HTML structure", "Bullet count",
                       "Length limits", "Required fields",
                       "fn_validate_fmt()"],
        "G4: Novelty": ["Cosine similarity", "&lt; 0.85 threshold",
                        "No duplicate slides", "Embedding compare",
                        "fn_check_novelty()"],
    }

    # Conveyor belt
    belt_y = HEIGHT - 70
    parts.append(rounded_rect(30, belt_y, WIDTH - 60, 20, Palette.BORDER, rx=4))
    # Rollers
    for rx in range(60, WIDTH - 60, 50):
        parts.append(circle(rx, belt_y + 20, 6, Palette.BG_CARD,
                            stroke=Palette.BORDER_LIGHT, stroke_width=1))

    # QC stations
    n = len(stations) if stations else 4
    station_w = 320
    total_w = n * station_w
    gap = (WIDTH - 80 - total_w) / max(n - 1, 1)
    station_h = belt_y - title_h - 30
    station_colors = [Palette.BLUE, Palette.GREEN, Palette.TEAL, Palette.PURPLE]

    for i in range(n):
        sx = 40 + i * (station_w + gap)
        sy = title_h + 10
        color = station_colors[i % len(station_colors)]
        label = stations[i].get("label", f"QC {i + 1}") if i < len(stations) else f"QC {i + 1}"

        # Station box
        parts.append(rounded_rect(sx, sy, station_w, station_h, Palette.BG_CARD,
                                   stroke=color, stroke_width=2, rx=10))

        # Colored accent bar at top
        parts.append(rounded_rect(sx, sy, station_w, 8, color, rx=0))

        # PG badge
        parts.append(circle(sx + station_w / 2, sy + 40, 22, Palette.PG_BLUE, opacity=0.9))
        parts.append(text(sx + station_w / 2, sy + 40, "PG",
                          font_size=24, weight="700", fill=Palette.TEXT_LIGHT))

        # Station label
        parts.append(text(sx + station_w / 2, sy + 85, label,
                          font_size=32, weight="700", fill=color))

        # Divider line
        parts.append(line(sx + 30, sy + 110, sx + station_w - 30, sy + 110,
                          Palette.BORDER_LIGHT, 1))

        # Gate detail bullets — evenly spaced to fill the station
        details = gate_details.get(label, ["Validates", "Checks quality", "SQL function"])
        n_details = len(details)
        detail_zone_top = sy + 120
        detail_zone_bottom = sy + station_h - 80
        detail_spacing = (detail_zone_bottom - detail_zone_top) / max(n_details, 1)
        for j, detail in enumerate(details):
            dy = detail_zone_top + j * detail_spacing + detail_spacing / 2
            # Bullet dot
            parts.append(circle(sx + 35, dy, 5, color, opacity=0.7))
            # Last item (fn_*) in monospace-style color
            is_fn = detail.startswith("fn_")
            fill = Palette.CYAN if is_fn else Palette.TEXT_MUTED
            weight = "600" if is_fn else "normal"
            parts.append(
                f'<text x="{sx + 50}" y="{dy}" font-size="28" '
                f'fill="{fill}" text-anchor="start" '
                f'dominant-baseline="middle" font-weight="{weight}">{detail}</text>'
            )

        # Pass indicator at bottom
        check_y = sy + station_h - 60
        parts.append(rounded_rect(sx + 60, check_y, station_w - 120, 40,
                                   Palette.BG_CARD, stroke=Palette.GREEN,
                                   stroke_width=1, rx=6))
        parts.append(text(sx + station_w / 2, check_y + 20, "✓ PASS",
                          font_size=26, fill=Palette.GREEN, weight="700"))

        # Slide item on conveyor
        slide_x = sx + station_w / 2 - 20
        parts.append(rounded_rect(slide_x, belt_y - 25, 40, 25,
                                   Palette.BG_CARD, stroke=color, stroke_width=1, rx=3))
        parts.append(text(slide_x + 20, belt_y - 12, "📄",
                          font_size=16, fill=Palette.TEXT_LIGHT))

        # Arrow between stations on belt
        if i < n - 1:
            arrow_x = sx + station_w + gap / 2
            parts.append(polygon(
                [(arrow_x - 8, belt_y + 3), (arrow_x + 8, belt_y + 10),
                 (arrow_x - 8, belt_y + 17)],
                fill=Palette.TEXT_DIM
            ))

    return svg_doc("\n".join(parts))


def _student_analogy(cfg: dict) -> str:
    """Stick figure with desk + book icons (before/after), scaled to fill canvas."""
    title = cfg.get("title", "")
    parts = []

    if title:
        parts.append(text(WIDTH / 2, 45, title, font_size=52, weight="700"))

    # Divider
    parts.append(line(WIDTH / 2, 80, WIDTH / 2, HEIGHT - 30,
                      Palette.BORDER_LIGHT, 2, dash="6,4"))

    for side, label, has_books in [("left", "Without RAG", False), ("right", "With RAG", True)]:
        cx = WIDTH / 4 if side == "left" else 3 * WIDTH / 4
        color = Palette.RED if side == "left" else Palette.GREEN

        # Label
        parts.append(text(cx, 105, label, font_size=38, weight="700", fill=color))

        # Stick figure — scaled up 1.6x
        head_y = 220
        head_r = 40
        parts.append(circle(cx, head_y, head_r, "none", stroke=Palette.TEXT_MUTED, stroke_width=3))
        # Body
        parts.append(line(cx, head_y + head_r, cx, head_y + 160, Palette.TEXT_MUTED, 3))
        # Arms
        parts.append(line(cx - 65, head_y + 80, cx + 65, head_y + 80, Palette.TEXT_MUTED, 3))
        # Legs
        parts.append(line(cx, head_y + 160, cx - 50, head_y + 240, Palette.TEXT_MUTED, 3))
        parts.append(line(cx, head_y + 160, cx + 50, head_y + 240, Palette.TEXT_MUTED, 3))

        # Desk
        desk_y = head_y + 225
        parts.append(line(cx - 160, desk_y, cx + 160, desk_y, Palette.BORDER_LIGHT, 4))

        if has_books:
            # Stack of books on desk — bigger
            book_colors = [Palette.BLUE, Palette.GREEN, Palette.TEAL, Palette.PURPLE]
            for bi in range(4):
                bx = cx - 90 + bi * 50
                by = desk_y - 32 - bi * 5
                parts.append(rounded_rect(bx, by, 45, 28, book_colors[bi], rx=3, opacity=0.7))
            # Happy face (smile)
            parts.append(path(f"M {cx - 16},{head_y + 8} Q {cx},{head_y + 24} {cx + 16},{head_y + 8}",
                              stroke=Palette.GREEN, stroke_width=3))
            # Speech bubble
            parts.append(rounded_rect(cx + 70, head_y - 75, 200, 55,
                                      Palette.BG_CARD, stroke=color, stroke_width=2, rx=10))
            parts.append(text(cx + 170, head_y - 48, "Cited answer!",
                              font_size=30, fill=color, weight="700"))

            # Explanation bullets below desk
            bullet_y = desk_y + 60
            bullets = [
                "✅ Retrieves real sources",
                "✅ Grounds response in facts",
                "✅ Cites where info came from",
                "✅ Reduces hallucination",
            ]
            for bi, b in enumerate(bullets):
                parts.append(text(cx, bullet_y + bi * 48, b,
                                  font_size=30, fill=Palette.TEXT_LIGHT, weight="500"))
        else:
            # Empty desk, confused face
            parts.append(text(cx, desk_y - 20, "?", font_size=44, fill=Palette.RED, weight="700"))
            # Worried face (frown)
            parts.append(path(f"M {cx - 16},{head_y + 16} Q {cx},{head_y} {cx + 16},{head_y + 16}",
                              stroke=Palette.RED, stroke_width=3))
            # Speech bubble
            parts.append(rounded_rect(cx + 70, head_y - 75, 220, 55,
                                      Palette.BG_CARD, stroke=color, stroke_width=2, rx=10))
            parts.append(text(cx + 180, head_y - 48, "Hallucination!",
                              font_size=30, fill=color, weight="700"))

            # Explanation bullets below desk
            bullet_y = desk_y + 60
            bullets = [
                "❌ No source material",
                "❌ Makes up plausible facts",
                "❌ No way to verify claims",
                "❌ Confident but wrong",
            ]
            for bi, b in enumerate(bullets):
                parts.append(text(cx, bullet_y + bi * 48, b,
                                  font_size=30, fill=Palette.TEXT_MUTED, weight="500"))

    return svg_doc("\n".join(parts))


def _bouncer_metaphor(cfg: dict) -> str:
    """MCP bouncer — approved vs rejected commands, large and readable."""
    title = cfg.get("title", "")
    parts = []

    title_h = 75 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    # MCP Bouncer in center — tall vertical bar
    bouncer_w = 200
    bouncer_h = HEIGHT - title_h - 40
    bouncer_x = WIDTH / 2 - bouncer_w / 2
    bouncer_y = title_h + 10
    parts.append(rounded_rect(bouncer_x, bouncer_y, bouncer_w, bouncer_h,
                               Palette.BG_CARD, stroke=Palette.PURPLE, stroke_width=3, rx=12))
    parts.append(text(WIDTH / 2, bouncer_y + bouncer_h / 2 - 25, "MCP",
                      font_size=52, weight="800", fill=Palette.PURPLE))
    parts.append(text(WIDTH / 2, bouncer_y + bouncer_h / 2 + 20, "Gateway",
                      font_size=32, fill=Palette.TEXT_MUTED))

    # Section headers
    left_cx = (bouncer_x) / 2 + 20
    right_cx = WIDTH / 2 + bouncer_w / 2 + (WIDTH - WIDTH / 2 - bouncer_w / 2) / 2

    parts.append(text(left_cx, title_h + 20, "✅ ALLOWED",
                      font_size=34, weight="700", fill=Palette.GREEN))
    parts.append(text(right_cx, title_h + 20, "🚫 BLOCKED",
                      font_size=34, weight="700", fill=Palette.RED))

    # Item dimensions
    item_w = bouncer_x - 80
    item_h = 80

    # Approved items (left side)
    approved = cfg.get("approved", ["search_chunks", "validate_slide"])
    n = len(approved)
    items_area_top = title_h + 60
    items_area_h = HEIGHT - items_area_top - 30
    items_block_h = n * item_h
    item_gap = min(30, (items_area_h - items_block_h) / max(n - 1, 1)) if n > 1 else 0
    total_h = items_block_h + (n - 1) * item_gap
    start_y = items_area_top + (items_area_h - total_h) / 2

    for i, item_label in enumerate(approved):
        ax = 40
        ay = start_y + i * (item_h + item_gap)
        # Item box
        parts.append(rounded_rect(ax, ay, item_w, item_h, Palette.BG_CARD,
                                   stroke=Palette.GREEN, stroke_width=2, rx=8))
        parts.append(
            f'<text x="{ax + 25}" y="{ay + item_h / 2}" font-size="32" '
            f'fill="{Palette.GREEN}" text-anchor="start" dominant-baseline="middle" '
            f'font-weight="600">✓  {item_label}</text>'
        )
        # Arrow to bouncer
        arr_y = ay + item_h / 2
        parts.append(line(ax + item_w, arr_y, bouncer_x, arr_y, Palette.GREEN, 2))
        parts.append(
            f'<polygon points="{bouncer_x},{arr_y} {bouncer_x - 10},{arr_y - 5} '
            f'{bouncer_x - 10},{arr_y + 5}" fill="{Palette.GREEN}"/>'
        )

    # Rejected items (right side)
    rejected = cfg.get("rejected", ["DROP TABLE", "raw SQL"])
    n_r = len(rejected)
    r_block_h = n_r * item_h
    r_gap = min(30, (items_area_h - r_block_h) / max(n_r - 1, 1)) if n_r > 1 else 0
    r_total_h = r_block_h + (n_r - 1) * r_gap
    r_start_y = items_area_top + (items_area_h - r_total_h) / 2
    r_x = WIDTH / 2 + bouncer_w / 2 + 40

    for i, item_label in enumerate(rejected):
        ry = r_start_y + i * (item_h + r_gap)
        # Item box
        parts.append(rounded_rect(r_x, ry, item_w, item_h, Palette.BG_CARD,
                                   stroke=Palette.RED, stroke_width=2, rx=8))
        parts.append(
            f'<text x="{r_x + 25}" y="{ry + item_h / 2}" font-size="32" '
            f'fill="{Palette.RED}" text-anchor="start" dominant-baseline="middle" '
            f'font-weight="600">✗  {item_label}</text>'
        )
        # Blocked line from bouncer
        arr_y = ry + item_h / 2
        brx = WIDTH / 2 + bouncer_w / 2
        parts.append(line(brx, arr_y, r_x, arr_y, Palette.RED, 2))
        # X block marker
        mid_x = (brx + r_x) / 2
        parts.append(text(mid_x, arr_y - 2, "✗", font_size=28, fill=Palette.RED, weight="700"))

    return svg_doc("\n".join(parts))


def _recursive_frames(cfg: dict) -> str:
    """Nested rectangles creating Droste/recursive frame effect."""
    title = cfg.get("title", "")
    depth = cfg.get("depth", 6)
    parts = []

    colors = [Palette.BLUE, Palette.TEAL, Palette.PURPLE,
              Palette.GREEN, Palette.ORANGE, Palette.CYAN]

    for i in range(depth):
        inset = i * 45
        x = 30 + inset
        y = 20 + inset
        w = WIDTH - 60 - 2 * inset
        h = HEIGHT - 40 - 2 * inset

        if w > 80 and h > 40:
            color = colors[i % len(colors)]
            parts.append(rounded_rect(x, y, w, h, "none",
                                       stroke=color, stroke_width=2, rx=CORNER_RADIUS,
                                       opacity=0.7 - i * 0.08))

            # Mini "slide" content indicator
            if i < depth - 1:
                # Title bar
                parts.append(rounded_rect(x + 10, y + 10, w - 20, 20,
                                           color, rx=4, opacity=0.1))
                parts.append(text(x + w / 2, y + 20, f"Slide {i + 1}",
                                  font_size=22, fill=color, opacity=0.5))

    # Center text
    parts.append(text(WIDTH / 2, HEIGHT / 2 - 10, "Meta-Recursive",
                      font_size=48, weight="700", fill=Palette.TEXT_LIGHT))
    parts.append(text(WIDTH / 2, HEIGHT / 2 + 28, "Slides about slides",
                      font_size=28, fill=Palette.TEXT_MUTED))

    if title:
        parts.append(text(WIDTH / 2, HEIGHT - 20, title,
                          font_size=28, fill=Palette.TEXT_DIM))

    return svg_doc("\n".join(parts))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

DECORATIVE_TEMPLATES = {
    # Section dividers
    "gradient_elephant_spotlight": _gradient_elephant_spotlight,
    "blueprint_circuit": _blueprint_circuit,
    "layered_waves": _layered_waves,
    "dashboard_shapes": _dashboard_shapes,
    "geometric_stage": _geometric_stage,
    # Illustrations
    "toolbox": _toolbox,
    "magnifying_glass": _magnifying_glass,
    "castle_fortress": _castle_fortress,
    # Metaphors
    "air_traffic_tower": _air_traffic_tower,
    "factory_assembly": _factory_assembly,
    "student_analogy": _student_analogy,
    "bouncer_metaphor": _bouncer_metaphor,
    "recursive_frames": _recursive_frames,
}


def render_decorative(template: str, cfg: dict) -> str:
    """Render a decorative/abstract SVG from template name and config."""
    fn = DECORATIVE_TEMPLATES.get(template)
    if not fn:
        raise ValueError(f"Unknown decorative template: {template}. "
                         f"Available: {list(DECORATIVE_TEMPLATES.keys())}")
    return fn(cfg)
