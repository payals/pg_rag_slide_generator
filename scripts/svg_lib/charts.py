"""
Chart and infographic templates for SVG generation.

Templates: venn_3, matrix_grid, pyramid, mind_map, checklist, stat_cards
"""

import math
from scripts.svg_lib.common import (
    Palette, WIDTH, HEIGHT, CORNER_RADIUS, CARD_RADIUS,
    svg_doc, escape_xml, rounded_rect, circle, ellipse,
    line, polygon, path, text, group,
    linear_gradient, labeled_box,
)


def _venn_3(cfg: dict) -> str:
    """Three-circle Venn diagram — centered below title."""
    circles_cfg = cfg.get("circles", [])
    center_label = cfg.get("center", "Hybrid")
    title = cfg.get("title", "")
    parts = []

    title_h = 80 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    # Center the Venn in the remaining space below the title
    avail_h = HEIGHT - title_h
    cx = WIDTH / 2
    cy = title_h + avail_h / 2 + 20
    r = 220
    offset = 120

    defaults = [
        {"color": Palette.BLUE, "label": "Circle 1"},
        {"color": Palette.GREEN, "label": "Circle 2"},
        {"color": Palette.ORANGE, "label": "Circle 3"},
    ]

    # Positions: top, bottom-left, bottom-right
    angles = [270, 150, 30]

    for i in range(min(3, len(circles_cfg) if circles_cfg else 3)):
        cfg_c = circles_cfg[i] if i < len(circles_cfg) else defaults[i]
        angle = math.radians(angles[i])
        ccx = cx + offset * math.cos(angle)
        ccy = cy + offset * math.sin(angle)
        color = cfg_c.get("color", defaults[i]["color"])
        label = cfg_c.get("label", defaults[i]["label"])

        parts.append(circle(ccx, ccy, r, color, opacity=0.2))
        parts.append(circle(ccx, ccy, r, "none", stroke=color, stroke_width=2))

        # Label outside the circle — with background pill for readability
        lx = cx + (r + offset + 30) * math.cos(angle)
        ly = cy + (r + offset + 30) * math.sin(angle)
        # Clamp to canvas
        ly = max(title_h + 15, min(HEIGHT - 20, ly))
        pill_w = max(len(label) * 16, 140)
        parts.append(rounded_rect(lx - pill_w / 2, ly - 20, pill_w, 40,
                                   Palette.BG_DARK, stroke=color,
                                   stroke_width=1, rx=20, opacity=0.9))
        parts.append(text(lx, ly, label, font_size=30, weight="600", fill=color))

    # Center label
    parts.append(text(cx, cy, center_label, font_size=36, weight="700",
                      fill=Palette.TEXT_LIGHT))

    return svg_doc("\n".join(parts))


def _matrix_grid(cfg: dict) -> str:
    """Matrix/grid with rows, columns, and check/X marks."""
    rows = cfg.get("rows", [])
    cols = cfg.get("cols", [])
    data = cfg.get("data", [])
    title = cfg.get("title", "")
    parts = []

    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700"))

    n_cols = len(cols)
    n_rows = len(rows)

    col_w = (WIDTH - 250) / max(n_cols, 1)
    avail_h = HEIGHT - 150
    row_h = avail_h / max(n_rows, 1)
    start_x = 220
    start_y = 100

    # Column headers
    for j, col_name in enumerate(cols):
        cx_pos = start_x + j * col_w + col_w / 2
        parts.append(text(cx_pos, start_y - 15, col_name,
                          font_size=28, weight="700", fill=Palette.BLUE))

    # Rows
    for i, row_name in enumerate(rows):
        y = start_y + i * row_h
        # Row label
        parts.append(text(200, y + row_h / 2, row_name,
                          font_size=28, weight="600", fill=Palette.TEXT_LIGHT,
                          anchor="end"))
        # Alternating row bg
        if i % 2 == 0:
            parts.append(rounded_rect(start_x - 5, y, n_cols * col_w + 10, row_h,
                                      Palette.BG_CARD, rx=4, opacity=0.5))

        # Cells
        for j in range(n_cols):
            cx_pos = start_x + j * col_w + col_w / 2
            if i < len(data) and j < len(data[i]):
                val = data[i][j]
                if val is True or val == "✓":
                    parts.append(text(cx_pos, y + row_h / 2, "✓",
                                      font_size=48, weight="700", fill=Palette.GREEN))
                elif val is False or val == "✗":
                    parts.append(text(cx_pos, y + row_h / 2, "✗",
                                      font_size=48, weight="700", fill=Palette.RED))
                else:
                    parts.append(text(cx_pos, y + row_h / 2, str(val),
                                      font_size=26, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts))


def _pyramid(cfg: dict) -> str:
    """Pyramid with N levels, widest at bottom — large fonts."""
    levels = cfg.get("levels", [])
    title = cfg.get("title", "")
    parts = []

    title_h = 75 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    n = len(levels)
    if n == 0:
        return svg_doc("\n".join(parts))

    colors = [Palette.BLUE, Palette.TEAL, Palette.GREEN, Palette.PURPLE, Palette.ORANGE]

    top_w = 200
    bottom_w = WIDTH - 100
    total_h = HEIGHT - title_h - 30
    start_y = title_h
    level_h = total_h / n

    cx = WIDTH / 2

    for i in range(n):
        # i=0 is top (smallest), i=n-1 is bottom (widest)
        t = i / max(n - 1, 1)
        w = top_w + (bottom_w - top_w) * t
        y = start_y + i * level_h
        x = cx - w / 2
        color = colors[(n - 1 - i) % len(colors)]
        level = levels[i]

        # Trapezoid: top edge narrower, bottom edge wider
        if i < n - 1:
            next_t = (i + 1) / max(n - 1, 1)
            next_w = top_w + (bottom_w - top_w) * next_t
        else:
            next_w = w

        x_top = cx - w / 2
        x_bot = cx - next_w / 2

        points = [
            (x_top, y),
            (x_top + w, y),
            (x_bot + next_w, y + level_h),
            (x_bot, y + level_h),
        ]
        parts.append(polygon(points, fill=color, opacity=0.8))
        parts.append(polygon(points, fill="none", stroke=Palette.BG_DARK, stroke_width=2))

        # Label — larger fonts, vertically centered in the level
        label = level.get("label", "")
        sublabel = level.get("sublabel", "")
        parts.append(text(cx, y + level_h / 2 - (14 if sublabel else 0),
                          label, font_size=40, weight="700", fill=Palette.TEXT_LIGHT))
        if sublabel:
            parts.append(text(cx, y + level_h / 2 + 26, sublabel,
                              font_size=30, fill=Palette.TEXT_LIGHT, opacity=0.8))

    return svg_doc("\n".join(parts))


def _mind_map(cfg: dict) -> str:
    """Mind map with center node and branches — scaled to fill canvas."""
    center = cfg.get("center", "Center")
    branches = cfg.get("branches", [])
    title = cfg.get("title", "")
    parts = []

    title_h = 70 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    cx, cy = WIDTH / 2, HEIGHT / 2 + (title_h - 10) / 2

    # Center node — large pill
    center_w = max(len(center) * 20, 240)
    center_h = 90
    parts.append(rounded_rect(cx - center_w / 2, cy - center_h / 2,
                               center_w, center_h, Palette.PG_BLUE,
                               stroke=Palette.BLUE, stroke_width=3,
                               rx=center_h // 2, opacity=0.9))
    parts.append(text(cx, cy, center, font_size=34, weight="700"))

    n = len(branches)
    colors = [Palette.BLUE, Palette.GREEN, Palette.ORANGE, Palette.PURPLE,
              Palette.TEAL, Palette.CYAN]

    # Use fixed angles for 4 branches: top, right, bottom, left
    fixed_angles = [-90, 0, 90, 180]

    for i, branch in enumerate(branches):
        angle_deg = fixed_angles[i] if i < len(fixed_angles) else 360 * i / n - 90
        angle = math.radians(angle_deg)
        # Horizontal branches need more distance (canvas is 1600 wide vs 900 tall)
        is_horizontal = abs(math.cos(angle)) > abs(math.sin(angle))
        br_dist = 440 if is_horizontal else 280
        bx = cx + br_dist * math.cos(angle)
        by = cy + br_dist * math.sin(angle)
        color = colors[i % len(colors)]

        # Compute branch pill dimensions
        br_label = branch.get("label", "")
        br_w = max(len(br_label) * 18, 150)
        br_h = 60

        # Line from center edge to branch pill edge
        if is_horizontal:
            edge_x = cx + (center_w / 2) * (1 if math.cos(angle) > 0 else -1)
            edge_y = cy
            line_end_x = bx - (br_w / 2) * (1 if math.cos(angle) > 0 else -1)
            line_end_y = by
        else:
            edge_x = cx
            edge_y = cy + (center_h / 2) * (1 if math.sin(angle) > 0 else -1)
            line_end_x = bx
            line_end_y = by - (br_h / 2) * (1 if math.sin(angle) > 0 else -1)
        parts.append(line(edge_x, edge_y, line_end_x, line_end_y, color, 3))

        # Branch node pill
        parts.append(rounded_rect(bx - br_w / 2, by - br_h / 2,
                                   br_w, br_h, Palette.BG_CARD,
                                   stroke=color, stroke_width=2, rx=br_h // 2))
        parts.append(text(bx, by, br_label,
                          font_size=30, weight="700", fill=color))

        # Sub-nodes — larger pills, wider spread
        children = branch.get("children", [])
        n_children = len(children)
        spread = 60  # degrees between sub-nodes
        for j, sub in enumerate(children):
            sub_offset = (j - (n_children - 1) / 2) * spread
            sub_angle = angle + math.radians(sub_offset)
            sub_dist = 180
            sx = bx + sub_dist * math.cos(sub_angle)
            sy = by + sub_dist * math.sin(sub_angle)

            # Pill dimensions
            pill_w = max(len(sub) * 16, 120)
            pill_h = 44

            # Clamp to canvas bounds
            sx = max(pill_w / 2 + 10, min(WIDTH - pill_w / 2 - 10, sx))
            sy = max(title_h + pill_h / 2 + 5, min(HEIGHT - pill_h / 2 - 5, sy))

            # Connector line from branch edge
            parts.append(line(bx + (br_w / 2) * math.cos(sub_angle),
                              by + (br_h / 2) * math.sin(sub_angle),
                              sx, sy, color, 2, dash="5,4"))

            # Sub-node pill
            parts.append(rounded_rect(sx - pill_w / 2, sy - pill_h / 2,
                                       pill_w, pill_h, Palette.BG_CARD,
                                       stroke=color, stroke_width=1, rx=pill_h // 2))
            parts.append(text(sx, sy, sub, font_size=26, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts))


def _checklist(cfg: dict) -> str:
    """Checklist with green checkmarks."""
    items = cfg.get("items", [])
    title = cfg.get("title", "")
    parts = []

    title_h = 70 if title else 20
    if title:
        parts.append(text(WIDTH / 2, 45, title, font_size=48, weight="700"))

    n = len(items)
    gap = 12
    avail_h = HEIGHT - title_h - 30
    item_h = (avail_h - (n - 1) * gap) / max(n, 1)
    start_y = title_h

    for i, item in enumerate(items):
        y = start_y + i * (item_h + gap)

        # Card background
        parts.append(rounded_rect(100, y, WIDTH - 200, item_h,
                                  Palette.BG_CARD, stroke=Palette.BORDER, stroke_width=1, rx=8))

        # Green check circle
        check_cx = 140
        check_cy = y + item_h / 2
        parts.append(circle(check_cx, check_cy, 16, Palette.GREEN, opacity=0.2))
        parts.append(circle(check_cx, check_cy, 16, "none", stroke=Palette.GREEN, stroke_width=2))
        # Checkmark path
        parts.append(path(
            f"M {check_cx - 6},{check_cy} L {check_cx - 2},{check_cy + 5} L {check_cx + 7},{check_cy - 5}",
            stroke=Palette.GREEN, stroke_width=2.5
        ))

        # Item text
        item_text = item.get("text", item) if isinstance(item, dict) else item
        parts.append(text(180, check_cy, item_text,
                          font_size=34, fill=Palette.TEXT_LIGHT, anchor="start", weight="500"))

    return svg_doc("\n".join(parts))


def _stat_cards(cfg: dict) -> str:
    """Metric/stat cards in a grid."""
    stats = cfg.get("stats", [])
    title = cfg.get("title", "")
    cols = cfg.get("cols", 3)
    parts = []

    title_h = 80 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 45, title, font_size=48, weight="700"))

    n = len(stats)
    gap = 20
    rows = (n + cols - 1) // cols

    # Compact card sizing — content-driven, not canvas-filling
    card_w = (WIDTH - 80 - (cols - 1) * gap) / cols
    card_h = 180  # Fixed height for tight, readable cards
    has_subtitle = any(stat.get("subtitle") for stat in stats)
    if has_subtitle:
        card_h = 200

    # Center the grid vertically in remaining space
    grid_h = rows * card_h + (rows - 1) * gap
    available_h = HEIGHT - title_h - 30
    start_y = title_h + (available_h - grid_h) / 2

    colors = [Palette.BLUE, Palette.GREEN, Palette.TEAL, Palette.PURPLE,
              Palette.ORANGE, Palette.CYAN]

    for i, stat in enumerate(stats):
        col = i % cols
        row = i // cols
        x = 40 + col * (card_w + gap)
        y = start_y + row * (card_h + gap)
        color = stat.get("color", colors[i % len(colors)])

        # Card bg
        parts.append(rounded_rect(x, y, card_w, card_h, Palette.BG_CARD,
                                  stroke=Palette.BORDER, stroke_width=1, rx=CARD_RADIUS))

        # Colored accent bar at top of card
        parts.append(
            f'<rect x="{x}" y="{y}" width="{card_w}" '
            f'height="4" rx="{CARD_RADIUS}" fill="{color}" />'
        )

        # Layout positions within card
        value_y = y + 70 if has_subtitle else y + card_h / 2 - 12
        label_y = value_y + 42
        subtitle_y = label_y + 32

        # Big number
        parts.append(text(x + card_w / 2, value_y,
                          str(stat.get("value", "0")),
                          font_size=66, weight="800", fill=color))

        # Label
        parts.append(text(x + card_w / 2, label_y,
                          stat.get("label", ""),
                          font_size=26, weight="600", fill=Palette.TEXT_LIGHT))

        # Subtitle (optional)
        subtitle = stat.get("subtitle", "")
        if subtitle:
            parts.append(text(x + card_w / 2, subtitle_y,
                              subtitle,
                              font_size=18, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

CHART_TEMPLATES = {
    "venn_3": _venn_3,
    "matrix_grid": _matrix_grid,
    "pyramid": _pyramid,
    "mind_map": _mind_map,
    "checklist": _checklist,
    "stat_cards": _stat_cards,
}


def render_chart(template: str, cfg: dict) -> str:
    """Render a chart/infographic SVG from template name and config."""
    fn = CHART_TEMPLATES.get(template)
    if not fn:
        raise ValueError(f"Unknown chart template: {template}. "
                         f"Available: {list(CHART_TEMPLATES.keys())}")
    return fn(cfg)
