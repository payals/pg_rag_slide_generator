"""
Diagram templates for SVG generation.

Templates: box_and_arrow, layered_boxes, split_comparison, concentric_rings,
card_grid, layer_stack, merge_flow, hub_spoke_horizontal, two_col_mapping,
horizontal_flow, nested_rects
"""

import math

from scripts.svg_lib.common import (
    Palette, WIDTH, HEIGHT, CORNER_RADIUS, CARD_RADIUS,
    svg_doc, escape_xml, rounded_rect, circle, ellipse,
    line, polygon, path, text, text_multiline, group,
    arrow_right, arrow_down, arrow_between,
    linear_gradient, labeled_box, card, cylinder,
)


def _box_and_arrow(cfg: dict) -> str:
    """System architecture with boxes and arrows."""
    components = cfg.get("components", [])
    title = cfg.get("title", "")
    n = len(components)

    parts = []

    # Title
    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700",
                          fill=Palette.TEXT_LIGHT))

    # Layout components in a grid-like arrangement
    # Center component (index 0 if exists) is larger
    if n == 0:
        return svg_doc("\n".join(parts))

    # For 5-component layout: center large, 4 around it
    if n >= 5:
        center = components[0]
        surrounding = components[1:5]

        # Center (large, cylinder for DB) — scaled for 1600x900
        cx, cy, cw, ch = 560, 265, 480, 345
        parts.append(cylinder(cx, cy, cw, ch, Palette.PG_BLUE, center["label"]))
        if center.get("sublabel"):
            parts.append(text(cx + cw / 2, cy + ch - 40, center["sublabel"],
                              font_size=24, fill=Palette.TEXT_MUTED))

        # Surrounding boxes: left, right, top, bottom — scaled for 1600x900
        positions = [
            (50, 350, 420, 110),      # left
            (1130, 350, 420, 110),    # right
            (590, 80, 420, 110),      # top
            (590, 700, 420, 110),     # bottom
        ]

        for i, (bx, by, bw, bh) in enumerate(positions):
            if i < len(surrounding):
                comp = surrounding[i]
                color = comp.get("color", Palette.BLUE)
                parts.append(labeled_box(bx, by, bw, bh, comp["label"],
                                         border_color=color, sublabel=comp.get("sublabel")))
                # Arrows to center
                if i == 0:  # left -> center
                    parts.append(arrow_right(bx + bw, by + bh / 2, cx, stroke=color))
                elif i == 1:  # center -> right
                    parts.append(arrow_right(cx + cw, by + bh / 2, bx, stroke=color))
                elif i == 2:  # top -> center
                    parts.append(arrow_down(bx + bw / 2, by + bh, cy, stroke=color))
                elif i == 3:  # center -> bottom
                    parts.append(arrow_down(bx + bw / 2, cy + ch, by, stroke=color))

    else:
        # Generic layout — 2-row wrapping when n > 3
        box_h = 110
        if n > 3:
            row1_n = math.ceil(n / 2)
            row2_n = n - row1_n
            box_w = min(260, (WIDTH - 80) / row1_n - 20)
            gap = 20

            # Row 1
            start_x1 = (WIDTH - (box_w * row1_n + gap * (row1_n - 1))) / 2
            y1 = HEIGHT / 2 - box_h - 30
            for i in range(row1_n):
                comp = components[i]
                bx = start_x1 + i * (box_w + gap)
                color = comp.get("color", Palette.BLUE)
                parts.append(labeled_box(bx, y1, box_w, box_h, comp["label"],
                                         border_color=color, sublabel=comp.get("sublabel")))
                if i < row1_n - 1:
                    parts.append(arrow_right(bx + box_w + 2, y1 + box_h / 2,
                                             bx + box_w + gap - 2, stroke=color))

            # Row 2
            start_x2 = (WIDTH - (box_w * row2_n + gap * (row2_n - 1))) / 2
            y2 = HEIGHT / 2 + 30
            for i in range(row2_n):
                comp = components[row1_n + i]
                bx = start_x2 + i * (box_w + gap)
                color = comp.get("color", Palette.BLUE)
                parts.append(labeled_box(bx, y2, box_w, box_h, comp["label"],
                                         border_color=color, sublabel=comp.get("sublabel")))
                if i < row2_n - 1:
                    parts.append(arrow_right(bx + box_w + 2, y2 + box_h / 2,
                                             bx + box_w + gap - 2, stroke=color))

            # Turn arrow: row1 last → row2 first
            last_r1_x = start_x1 + (row1_n - 1) * (box_w + gap) + box_w / 2
            first_r2_x = start_x2 + box_w / 2
            mid_y = (y1 + box_h + y2) / 2
            turn_color = components[row1_n - 1].get("color", Palette.BLUE)
            parts.append(path(
                f"M {last_r1_x},{y1 + box_h} L {last_r1_x},{mid_y} L {first_r2_x},{mid_y} L {first_r2_x},{y2}",
                stroke=turn_color, stroke_width=2
            ))
            # Arrowhead at end of turn
            parts.append(polygon(
                [(first_r2_x, y2),
                 (first_r2_x - 5, y2 - 8),
                 (first_r2_x + 5, y2 - 8)],
                fill=turn_color
            ))
        else:
            box_w = min(260, (WIDTH - 80) / n - 20)
            start_x = (WIDTH - (box_w * n + 20 * (n - 1))) / 2
            y_pos = HEIGHT / 2 - box_h / 2

            for i, comp in enumerate(components):
                bx = start_x + i * (box_w + 20)
                color = comp.get("color", Palette.BLUE)
                parts.append(labeled_box(bx, y_pos, box_w, box_h, comp["label"],
                                         border_color=color, sublabel=comp.get("sublabel")))
                if i < n - 1:
                    parts.append(arrow_right(bx + box_w + 2, y_pos + box_h / 2,
                                             bx + box_w + 18, stroke=color))

    return svg_doc("\n".join(parts))


def _layered_boxes(cfg: dict) -> str:
    """Stacked platform layers with bridges."""
    layers = cfg.get("layers", [])
    title = cfg.get("title", "")
    parts = []

    title_h = 55 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700"))

    n = len(layers)
    gap = 15
    avail_h = HEIGHT - title_h - 40  # top/bottom padding
    layer_h = (avail_h - (n - 1) * gap) / max(n, 1)
    start_y = title_h

    colors = [Palette.BLUE, Palette.TEAL, Palette.PURPLE, Palette.GREEN, Palette.ORANGE]

    for i, layer in enumerate(layers):
        y = start_y + i * (layer_h + gap)
        # Offset for 3D effect
        offset = i * 15
        w = WIDTH - 160 - offset * 2
        x = 80 + offset
        color = colors[i % len(colors)]

        # Shadow
        parts.append(rounded_rect(x + 4, y + 4, w, layer_h, "#000", opacity=0.3, rx=8))
        # Main layer
        parts.append(rounded_rect(x, y, w, layer_h, Palette.BG_CARD,
                                  stroke=color, stroke_width=2, rx=8))
        # Label
        lbl = layer.get("label", f"Layer {i + 1}")
        parts.append(text(x + w / 2, y + layer_h / 2, lbl,
                          font_size=44, weight="600", fill=color))

        # Bridges (vertical connectors)
        if i < n - 1:
            parts.append(line(WIDTH / 2, y + layer_h, WIDTH / 2,
                              y + layer_h + gap, Palette.TEXT_DIM, 2, dash="4,4"))

    return svg_doc("\n".join(parts))


def _split_comparison(cfg: dict) -> str:
    """Left/right comparison layout — items fill the full card height."""
    left = cfg.get("left", {})
    right = cfg.get("right", {})
    title = cfg.get("title", "")
    parts = []

    title_h = 70 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    card_top = title_h
    card_h = HEIGHT - card_top - 30
    card_w = WIDTH / 2 - 55

    # Divider line
    parts.append(line(WIDTH / 2, title_h, WIDTH / 2, HEIGHT - 20,
                      Palette.BORDER_LIGHT, 2, dash="6,4"))

    # "VS" badge
    vs_y = card_top + card_h / 2
    parts.append(circle(WIDTH / 2, vs_y, 28, Palette.BG_DARK))
    parts.append(circle(WIDTH / 2, vs_y, 26, Palette.BORDER_LIGHT))
    parts.append(text(WIDTH / 2, vs_y, "VS", font_size=24, weight="700",
                      fill=Palette.TEXT_MUTED))

    # Auto-size items and center vertically within card
    max_items = max(len(left.get("items", [])), len(right.get("items", [])), 1)
    section_title_h = 65  # space for the side title
    items_area_top = card_top + section_title_h
    items_area_h = card_h - section_title_h
    line_h = min(80, items_area_h / (max_items + 1))
    font_sz = min(36, int(line_h * 0.55))
    # Center the block of items in the available area
    items_block_h = (max_items - 1) * line_h
    items_start_y = items_area_top + (items_area_h - items_block_h) / 2

    for side_cfg, cx_center, x_off in [
        (left, WIDTH / 4, 30),
        (right, 3 * WIDTH / 4, WIDTH / 2 + 25),
    ]:
        side_color = side_cfg.get("color", Palette.BLUE)

        # Card background
        parts.append(rounded_rect(x_off, card_top, card_w, card_h,
                                   Palette.BG_CARD, stroke=side_color, stroke_width=2,
                                   rx=CARD_RADIUS))

        # Side title
        parts.append(text(cx_center, card_top + 38, side_cfg.get("title", ""),
                          font_size=48, weight="700", fill=side_color))

        # Items — evenly distributed
        items = side_cfg.get("items", [])
        for i, item in enumerate(items):
            parts.append(text(cx_center, items_start_y + i * line_h, item,
                              font_size=font_sz, fill=Palette.TEXT_LIGHT))

    return svg_doc("\n".join(parts))


def _concentric_rings(cfg: dict) -> str:
    """Concentric ring diagram with configurable colors per ring."""
    rings = cfg.get("rings", [])
    title = cfg.get("title", "")
    parts = []

    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    cx, cy = WIDTH / 2, HEIGHT / 2 + 25
    max_r = min(WIDTH, HEIGHT) / 2 - 70
    n = len(rings)

    default_colors = [Palette.BLUE, Palette.TEAL, Palette.PG_BLUE,
                      Palette.ORANGE, Palette.PURPLE]

    for i in range(n - 1, -1, -1):
        r = max_r * (i + 1) / n
        ring = rings[i]
        color = ring.get("color", default_colors[i % len(default_colors)])

        # Ring fill (semi-transparent)
        parts.append(circle(cx, cy, r, f"{color}", opacity=0.12))
        parts.append(circle(cx, cy, r, "none", stroke=color, stroke_width=2))

        # Label — larger fonts, positioned in the band
        label = ring.get("label", "")
        if i == 0:
            # Center label
            parts.append(text(cx, cy, label,
                              font_size=32, weight="700", fill=color))
        else:
            label_y = cy - r + (max_r / n) / 2
            fs = 30 if len(label) < 40 else 26
            parts.append(text(cx, label_y, label,
                              font_size=fs, weight="600", fill=color))

    return svg_doc("\n".join(parts))


def _card_grid(cfg: dict) -> str:
    """Grid of cards (2xN or 3xN)."""
    cards = cfg.get("cards", [])
    title = cfg.get("title", "")
    cols = cfg.get("cols", 3)
    parts = []

    title_h = 55 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700"))

    n = len(cards)
    rows = (n + cols - 1) // cols
    gap = 16
    card_w = (WIDTH - 80 - (cols - 1) * gap) / cols
    card_h = (HEIGHT - title_h - 30 - (rows - 1) * gap) / max(rows, 1)
    start_y = title_h

    colors = [Palette.BLUE, Palette.TEAL, Palette.GREEN, Palette.PURPLE,
              Palette.ORANGE, Palette.CYAN]

    for i, c in enumerate(cards):
        col = i % cols
        row = i // cols
        x = 40 + col * (card_w + gap)
        y = start_y + row * (card_h + gap)
        accent = c.get("color", colors[i % len(colors)])
        body = c.get("body", [])
        if isinstance(body, str):
            body = [body]
        parts.append(card(x, y, card_w, card_h, c.get("title", ""),
                          body, accent_color=accent))

    return svg_doc("\n".join(parts))


def _layer_stack(cfg: dict) -> str:
    """Horizontal layer stack (bottom to top)."""
    layers = cfg.get("layers", [])
    title = cfg.get("title", "")
    parts = []

    title_h = 55 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700"))

    n = len(layers)
    gap = 8
    avail_h = HEIGHT - title_h - 30
    layer_h = (avail_h - (n - 1) * gap) / max(n, 1)
    start_y = title_h

    colors = [Palette.BLUE, Palette.TEAL, Palette.GREEN, Palette.PURPLE, Palette.ORANGE]

    for i, layer in enumerate(layers):
        # Bottom to top: index 0 is bottom
        y = start_y + (n - 1 - i) * (layer_h + gap)
        color = colors[i % len(colors)]
        w = WIDTH - 200

        parts.append(rounded_rect(100, y, w, layer_h, Palette.BG_CARD,
                                  stroke=color, stroke_width=2, rx=6))
        # Colored left accent bar
        parts.append(f'<rect x="100" y="{y}" width="6" height="{layer_h}" rx="3" fill="{color}"/>')
        parts.append(text(WIDTH / 2, y + layer_h / 2,
                          layer.get("label", f"Layer {i + 1}"),
                          font_size=44, weight="600", fill=Palette.TEXT_LIGHT))

    return svg_doc("\n".join(parts))


def _merge_flow(cfg: dict) -> str:
    """Multiple inputs merging into a single output — centered layout."""
    inputs = cfg.get("inputs", [])
    merger = cfg.get("merger", "Merge")
    output = cfg.get("output", "Result")
    title = cfg.get("title", "")
    parts = []

    title_h = 80 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    n = len(inputs)
    # Sizing — wider boxes to fit labels
    input_w, input_h = 380, 90
    merge_w, merge_h = 240, 100
    out_w, out_h = 300, 90
    gap = 80  # horizontal gap between columns

    # Total width of the three columns + gaps
    total_w = input_w + gap + merge_w + gap + out_w
    start_x = (WIDTH - total_w) / 2

    input_x = start_x
    merge_x = input_x + input_w + gap
    out_x = merge_x + merge_w + gap

    # Vertical centering in remaining space
    avail_h = HEIGHT - title_h
    mid_y = title_h + avail_h / 2
    merge_y = mid_y - merge_h / 2
    out_y = mid_y - out_h / 2

    colors = [Palette.BLUE, Palette.TEAL, Palette.ORANGE, Palette.GREEN]

    # Input boxes — evenly spaced vertically
    for i, inp in enumerate(inputs):
        y = title_h + 30 + i * (avail_h - 60 - input_h) / max(n - 1, 1)
        color = colors[i % len(colors)]
        parts.append(labeled_box(input_x, y, input_w, input_h,
                                 inp.get("label", ""),
                                 border_color=color))
        # Arrow to merger
        parts.append(arrow_between(input_x + input_w, y + input_h / 2,
                                   merge_x, merge_y + merge_h / 2,
                                   stroke=color))

    # Merger box
    parts.append(labeled_box(merge_x, merge_y, merge_w, merge_h, merger,
                             border_color=Palette.PURPLE,
                             fill=Palette.BG_CARD))

    # Arrow to output
    parts.append(arrow_right(merge_x + merge_w, merge_y + merge_h / 2,
                             out_x, stroke=Palette.GREEN))

    # Output box
    parts.append(labeled_box(out_x, out_y, out_w, out_h, output,
                             border_color=Palette.GREEN))

    return svg_doc("\n".join(parts))


def _hub_spoke_horizontal(cfg: dict) -> str:
    """Hub in center with spokes to left and right — properly connected."""
    hub = cfg.get("hub", {})
    left_items = cfg.get("left", [])
    right_items = cfg.get("right", [])
    title = cfg.get("title", "")
    parts = []

    title_h = 75 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    # Hub in center
    hub_w, hub_h = 300, 160
    hub_x = WIDTH / 2 - hub_w / 2
    hub_y = HEIGHT / 2 - hub_h / 2
    hub_color = hub.get("color", Palette.PURPLE)
    parts.append(labeled_box(hub_x, hub_y, hub_w, hub_h, hub.get("label", "Hub"),
                             border_color=hub_color, font_size=34))

    # Left side label
    parts.append(text(200, title_h + 10, "LLM Clients",
                      font_size=28, weight="600", fill=Palette.TEXT_MUTED))

    # Right side label
    parts.append(text(WIDTH - 200, title_h + 10, "Data Sources",
                      font_size=28, weight="600", fill=Palette.TEXT_MUTED))

    # Spoke item dimensions — larger
    item_w, item_h = 280, 80

    # Left spokes
    n_left = len(left_items)
    avail_h = HEIGHT - title_h - 60
    left_start = title_h + 40
    left_gap = (avail_h - n_left * item_h) / max(n_left - 1, 1) if n_left > 1 else 0
    for i, item in enumerate(left_items):
        iy = left_start + i * (item_h + left_gap)
        color = item.get("color", Palette.BLUE)
        parts.append(labeled_box(40, iy, item_w, item_h, item.get("label", ""),
                                 border_color=color, font_size=32))
        # Arrow from item center-right to hub center-left
        start_x = 40 + item_w
        start_y = iy + item_h / 2
        end_x = hub_x
        end_y = hub_y + hub_h / 2
        parts.append(
            f'<line x1="{start_x}" y1="{start_y}" x2="{end_x}" y2="{end_y}" '
            f'stroke="{color}" stroke-width="2.5"/>'
        )
        parts.append(
            f'<polygon points="{end_x},{end_y} {end_x - 10},{end_y - 5} '
            f'{end_x - 10},{end_y + 5}" fill="{color}"/>'
        )

    # Right spokes
    n_right = len(right_items)
    right_start = title_h + 40
    right_gap = (avail_h - n_right * item_h) / max(n_right - 1, 1) if n_right > 1 else 0
    for i, item in enumerate(right_items):
        iy = right_start + i * (item_h + right_gap)
        color = item.get("color", Palette.GREEN)
        parts.append(labeled_box(WIDTH - 40 - item_w, iy, item_w, item_h,
                                 item.get("label", ""), border_color=color, font_size=32))
        # Arrow from hub center-right to item center-left
        start_x = hub_x + hub_w
        start_y = hub_y + hub_h / 2
        end_x = WIDTH - 40 - item_w
        end_y = iy + item_h / 2
        parts.append(
            f'<line x1="{start_x}" y1="{start_y}" x2="{end_x}" y2="{end_y}" '
            f'stroke="{color}" stroke-width="2.5"/>'
        )
        parts.append(
            f'<polygon points="{end_x},{end_y} {end_x - 10},{end_y - 5} '
            f'{end_x - 10},{end_y + 5}" fill="{color}"/>'
        )

    return svg_doc("\n".join(parts))


def _two_col_mapping(cfg: dict) -> str:
    """Two-column mapping with connecting lines."""
    left_items = cfg.get("left", [])
    right_items = cfg.get("right", [])
    title = cfg.get("title", "")
    parts = []

    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700"))

    # Left header
    parts.append(text(300, 70, cfg.get("left_header", "Source"),
                      font_size=34, weight="700", fill=Palette.BLUE))
    # Right header
    parts.append(text(1300, 70, cfg.get("right_header", "Target"),
                      font_size=34, weight="700", fill=Palette.GREEN))

    n = max(len(left_items), len(right_items))
    gap = 16
    avail_h = HEIGHT - 100 - 30  # after headers, before bottom
    item_h = (avail_h - (n - 1) * gap) / max(n, 1)
    item_w = 400
    start_y = 100

    for i in range(n):
        y = start_y + i * (item_h + gap)

        # Left item
        if i < len(left_items):
            li = left_items[i]
            parts.append(labeled_box(100, y, item_w, item_h,
                                     li.get("label", ""), border_color=Palette.BLUE))

        # Right item
        if i < len(right_items):
            ri = right_items[i]
            color = ri.get("color", Palette.GREEN)
            parts.append(labeled_box(1100, y, item_w, item_h,
                                     ri.get("label", ""), border_color=color))
            # Lock icon
            if ri.get("locked"):
                parts.append(text(1080, y + item_h / 2, "🔒", font_size=30))

        # Connecting line
        if i < len(left_items) and i < len(right_items):
            parts.append(arrow_right(500, y + item_h / 2, 1100, stroke=Palette.TEXT_DIM))

    return svg_doc("\n".join(parts))


def _horizontal_flow(cfg: dict) -> str:
    """Horizontal flow/pipeline (conveyor belt style)."""
    steps = cfg.get("steps", [])
    title = cfg.get("title", "")
    parts = []

    if title:
        parts.append(text(WIDTH / 2, 35, title, font_size=48, weight="700"))

    n = len(steps)
    if n == 0:
        return svg_doc("\n".join(parts))

    # Conveyor belt base - positioned lower
    belt_y = HEIGHT - 80
    parts.append(rounded_rect(40, belt_y, WIDTH - 80, 30, Palette.BORDER, rx=4))
    # Belt track lines
    for bx in range(60, WIDTH - 60, 30):
        parts.append(line(bx, belt_y + 8, bx + 15, belt_y + 8, Palette.TEXT_DIM, 1))

    colors = [Palette.BLUE, Palette.TEAL, Palette.GREEN, Palette.PURPLE]

    if n > 3:
        # 2-row wrapping
        row1_n = math.ceil(n / 2)
        row2_n = n - row1_n
        step_w = min(280, (WIDTH - 100) / row1_n - 20)
        gap = 20
        row_h = (belt_y - 90 - 30) / 2  # split available height

        # Row 1
        start_x1 = (WIDTH - (step_w * row1_n + gap * (row1_n - 1))) / 2
        y1 = 70
        for i in range(row1_n):
            step = steps[i]
            x = start_x1 + i * (step_w + gap)
            color = colors[i % len(colors)]
            parts.append(labeled_box(x, y1, step_w, row_h, step.get("label", ""),
                                     border_color=color, sublabel=step.get("sublabel")))
            if i < row1_n - 1:
                parts.append(arrow_right(x + step_w + 2, y1 + row_h / 2,
                                         x + step_w + gap - 2, stroke=Palette.TEXT_DIM))

        # Row 2
        start_x2 = (WIDTH - (step_w * row2_n + gap * (row2_n - 1))) / 2
        y2 = 70 + row_h + 30
        for i in range(row2_n):
            step = steps[row1_n + i]
            x = start_x2 + i * (step_w + gap)
            color = colors[(row1_n + i) % len(colors)]
            parts.append(labeled_box(x, y2, step_w, row_h, step.get("label", ""),
                                     border_color=color, sublabel=step.get("sublabel")))
            # Vertical line to belt
            parts.append(line(x + step_w / 2, y2 + row_h, x + step_w / 2,
                              belt_y, color, 2, dash="4,4"))
            if i < row2_n - 1:
                parts.append(arrow_right(x + step_w + 2, y2 + row_h / 2,
                                         x + step_w + gap - 2, stroke=Palette.TEXT_DIM))

        # Turn arrow from row1 last to row2 first
        last_r1_x = start_x1 + (row1_n - 1) * (step_w + gap) + step_w / 2
        first_r2_x = start_x2 + step_w / 2
        mid_y = y1 + row_h + 15
        turn_color = colors[(row1_n - 1) % len(colors)]
        parts.append(path(
            f"M {last_r1_x},{y1 + row_h} L {last_r1_x},{mid_y} L {first_r2_x},{mid_y} L {first_r2_x},{y2}",
            stroke=turn_color, stroke_width=2
        ))
        parts.append(polygon(
            [(first_r2_x, y2), (first_r2_x - 5, y2 - 8), (first_r2_x + 5, y2 - 8)],
            fill=turn_color
        ))
    else:
        step_w = min(280, (WIDTH - 100) / n - 20)
        step_h = belt_y - 90  # fill from title to belt
        start_x = (WIDTH - (step_w * n + 20 * (n - 1))) / 2
        step_y = 70

        for i, step in enumerate(steps):
            x = start_x + i * (step_w + 20)
            color = colors[i % len(colors)]
            parts.append(labeled_box(x, step_y, step_w, step_h, step.get("label", ""),
                                     border_color=color, sublabel=step.get("sublabel")))
            # Vertical line to belt
            parts.append(line(x + step_w / 2, step_y + step_h, x + step_w / 2,
                              belt_y, color, 2, dash="4,4"))

            if i < n - 1:
                parts.append(arrow_right(x + step_w + 2, step_y + step_h / 2,
                                         x + step_w + 18, stroke=Palette.TEXT_DIM))

    return svg_doc("\n".join(parts))


def _nested_rects(cfg: dict) -> str:
    """Defense-in-depth: layered security barriers with descriptions."""
    labels = cfg.get("labels", [])
    title = cfg.get("title", "")
    parts = []

    title_h = 75 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    n = len(labels)
    colors = [Palette.BLUE, Palette.TEAL, Palette.GREEN, Palette.PURPLE, Palette.ORANGE]
    icons = ["🛡️", "🔒", "🔍", "⚙️", "🔑"]

    # Descriptions for common schema security layers
    descriptions = {
        "REVOKE public schema access": "Block all default permissions",
        "SECURITY INVOKER functions": "Run as caller, not definer",
        "SET search_path = pg_catalog, public": "Prevent schema injection",
        "Typed function interfaces only": "No raw SQL — only typed tools",
    }

    # Layout: vertical stack of barrier bars
    bar_h = 100
    gap = 30
    total_h = n * bar_h + (n - 1) * gap
    start_y = title_h + (HEIGHT - title_h - total_h) / 2
    bar_x = 80
    bar_w = WIDTH - 160

    # Top label: incoming request
    parts.append(text(WIDTH / 2, start_y - 30, "⬇  LLM Request",
                      font_size=28, weight="600", fill=Palette.TEXT_DIM))

    for i in range(n):
        y = start_y + i * (bar_h + gap)
        color = colors[i % len(colors)]
        label_text = labels[i] if i < len(labels) else f"Layer {i + 1}"
        icon = icons[i % len(icons)]
        desc = descriptions.get(label_text, "")

        # Barrier bar with filled background
        parts.append(rounded_rect(bar_x, y, bar_w, bar_h, Palette.BG_CARD,
                                   stroke=color, stroke_width=3, rx=12))

        # Colored left accent
        parts.append(rounded_rect(bar_x, y, 8, bar_h, color, rx=0))

        # Icon
        parts.append(text(bar_x + 50, y + bar_h / 2, icon,
                          font_size=36, fill=color))

        # Layer label — left side
        parts.append(
            f'<text x="{bar_x + 90}" y="{y + bar_h / 2 - (12 if desc else 0)}" '
            f'font-size="32" fill="{color}" text-anchor="start" '
            f'dominant-baseline="middle" font-weight="700">{label_text}</text>'
        )

        # Description — below label
        if desc:
            parts.append(
                f'<text x="{bar_x + 90}" y="{y + bar_h / 2 + 18}" '
                f'font-size="24" fill="{Palette.TEXT_MUTED}" text-anchor="start" '
                f'dominant-baseline="middle" font-weight="normal">{desc}</text>'
            )

        # Status badge on right
        parts.append(rounded_rect(bar_x + bar_w - 180, y + bar_h / 2 - 18,
                                   140, 36, Palette.BG_DARK,
                                   stroke=color, stroke_width=1, rx=18))
        parts.append(text(bar_x + bar_w - 110, y + bar_h / 2,
                          "✓ ENFORCED", font_size=20, weight="600", fill=color))

        # Down arrow between layers
        if i < n - 1:
            arrow_y = y + bar_h + gap / 2
            parts.append(text(WIDTH / 2, arrow_y, "⬇",
                              font_size=24, fill=Palette.TEXT_DIM))

    # Bottom label: safe data access
    parts.append(text(WIDTH / 2, start_y + total_h + 30,
                      "⬇  Safe Data Access (PostgreSQL)",
                      font_size=28, weight="600", fill=Palette.GREEN))

    return svg_doc("\n".join(parts))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

DIAGRAM_TEMPLATES = {
    "box_and_arrow": _box_and_arrow,
    "layered_boxes": _layered_boxes,
    "split_comparison": _split_comparison,
    "concentric_rings": _concentric_rings,
    "card_grid": _card_grid,
    "layer_stack": _layer_stack,
    "merge_flow": _merge_flow,
    "hub_spoke_horizontal": _hub_spoke_horizontal,
    "two_col_mapping": _two_col_mapping,
    "horizontal_flow": _horizontal_flow,
    "nested_rects": _nested_rects,
}


def render_diagram(template: str, cfg: dict) -> str:
    """Render a diagram SVG from template name and config."""
    fn = DIAGRAM_TEMPLATES.get(template)
    if not fn:
        raise ValueError(f"Unknown diagram template: {template}. "
                         f"Available: {list(DIAGRAM_TEMPLATES.keys())}")
    return fn(cfg)
