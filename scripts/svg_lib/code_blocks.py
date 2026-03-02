"""
Code editor and database table mockup templates.

Templates: code_editor, code_editor_split, db_table, multi_panel
"""

from scripts.svg_lib.common import (
    Palette, WIDTH, HEIGHT, CORNER_RADIUS, CARD_RADIUS,
    svg_doc, escape_xml, rounded_rect, circle, line, text, group,
)


# ---------------------------------------------------------------------------
# Syntax highlighting helpers
# ---------------------------------------------------------------------------

# Simple keyword categories for SQL-like highlighting
SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "ORDER", "BY", "INSERT", "INTO", "VALUES",
    "UPDATE", "SET", "DELETE", "CREATE", "FUNCTION", "RETURNS", "AS", "BEGIN",
    "END", "RETURN", "IF", "THEN", "ELSE", "ELSIF", "DECLARE", "LANGUAGE",
    "SECURITY", "INVOKER", "DEFINER", "IMMUTABLE", "STABLE", "VOLATILE",
    "JOIN", "LEFT", "RIGHT", "INNER", "ON", "AND", "OR", "NOT", "IN",
    "EXISTS", "CASE", "WHEN", "GROUP", "HAVING", "LIMIT", "OFFSET",
    "TABLE", "INDEX", "TYPE", "ENUM", "WITH", "RECURSIVE", "UNION",
    "ALL", "DISTINCT", "ASC", "DESC", "NULLS", "FIRST", "LAST",
    "REVOKE", "GRANT", "ALTER", "DROP", "CASCADE", "RESTRICT",
    "SEARCH_PATH", "SET", "RESET", "SHOW", "EXPLAIN", "ANALYZE",
    "COALESCE", "CAST", "ARRAY", "TEXT", "INTEGER", "BOOLEAN",
    "FLOAT", "NUMERIC", "UUID", "JSONB", "VECTOR", "TRIGGER",
    "PROCEDURE", "EXECUTE", "PERFORM", "RAISE", "NOTICE", "EXCEPTION",
}

JSON_KEYWORDS = {"true", "false", "null"}

COLORS = {
    "keyword": "#c792ea",   # purple
    "string": "#c3e88d",    # green
    "number": "#f78c6c",    # orange
    "comment": "#546e7a",   # gray
    "function": "#82aaff",  # blue
    "type": "#ffcb6b",      # yellow
    "operator": "#89ddff",  # cyan
    "default": "#d6deeb",   # light
}


def _highlight_sql_line(line_text: str) -> list[tuple[str, str]]:
    """Simple SQL tokenizer returning (text, color) pairs."""
    tokens = []
    words = line_text.split(" ")
    for word in words:
        upper = word.upper().strip("(),;:'\"")
        if word.strip().startswith("--"):
            tokens.append((word + " ", COLORS["comment"]))
        elif upper in SQL_KEYWORDS:
            tokens.append((word + " ", COLORS["keyword"]))
        elif word.startswith("'") or word.startswith('"'):
            tokens.append((word + " ", COLORS["string"]))
        elif word.replace(".", "").replace("-", "").isdigit():
            tokens.append((word + " ", COLORS["number"]))
        elif "(" in word and not word.startswith("("):
            # Function call
            fname = word.split("(")[0]
            rest = word[len(fname):]
            tokens.append((fname, COLORS["function"]))
            tokens.append((rest + " ", COLORS["default"]))
        elif word.startswith("$") or word.startswith("@"):
            tokens.append((word + " ", COLORS["type"]))
        elif word in ("->", "<->", "=>", "||", "&&", "::", "<=", ">="):
            tokens.append((word + " ", COLORS["operator"]))
        else:
            tokens.append((word + " ", COLORS["default"]))
    return tokens


def _render_code_lines(x: float, y: float, code_lines: list[str],
                       font_size: float = 32, line_height: float = 46,
                       show_line_numbers: bool = True,
                       language: str = "sql") -> str:
    """Render code with syntax highlighting and optional line numbers."""
    parts = []
    for i, code_line in enumerate(code_lines):
        ly = y + i * line_height

        # Line number
        if show_line_numbers:
            parts.append(text(x - 5, ly, str(i + 1), font_size=font_size - 2,
                              fill=Palette.TEXT_DIM, anchor="end",
                              font_family="'JetBrains Mono', 'Fira Code', monospace"))

        # Highlighted tokens
        tokens = _highlight_sql_line(code_line)
        offset = x + (5 if show_line_numbers else 0)
        char_w = font_size * 0.6  # approximate monospace char width

        for token_text, color in tokens:
            parts.append(
                f'<text x="{offset}" y="{ly}" font-size="{font_size}" '
                f'fill="{color}" text-anchor="start" dominant-baseline="middle" '
                f'font-family="\'JetBrains Mono\', \'Fira Code\', monospace">'
                f'{escape_xml(token_text)}</text>'
            )
            offset += len(token_text) * char_w

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def _code_editor(cfg: dict) -> str:
    """Dark-themed code editor mockup."""
    code_lines = cfg.get("code", [])
    title = cfg.get("title", "")
    filename = cfg.get("filename", "query.sql")
    annotations = cfg.get("annotations", [])
    language = cfg.get("language", "sql")
    parts = []

    # Window chrome
    win_x, win_y = 60, 30
    win_w, win_h = WIDTH - 120, HEIGHT - 60

    # Window background
    parts.append(rounded_rect(win_x, win_y, win_w, win_h,
                               Palette.BG_CODE, stroke=Palette.BORDER, stroke_width=1, rx=10))

    # Title bar
    parts.append(rounded_rect(win_x, win_y, win_w, 36, "#161b22", rx=10))
    # Fix bottom corners of title bar
    parts.append(f'<rect x="{win_x}" y="{win_y + 20}" width="{win_w}" height="16" fill="#161b22"/>')

    # Traffic lights
    parts.append(circle(win_x + 20, win_y + 18, 6, "#ff5f57"))
    parts.append(circle(win_x + 40, win_y + 18, 6, "#febc2e"))
    parts.append(circle(win_x + 60, win_y + 18, 6, "#28c840"))

    # Filename
    parts.append(text(win_x + win_w / 2, win_y + 18, filename,
                      font_size=22, fill=Palette.TEXT_MUTED,
                      font_family="'JetBrains Mono', monospace"))

    # Code area
    code_x = win_x + 50
    code_y = win_y + 60
    parts.append(_render_code_lines(code_x, code_y, code_lines,
                                    language=language))

    # Annotations (callout arrows/labels on the right)
    code_lh = 46  # must match _render_code_lines default line_height
    for ann in annotations:
        ann_line = ann.get("line", 1)
        ann_text = ann.get("text", "")
        ann_color = ann.get("color", Palette.TEAL)
        ay = code_y + (ann_line - 1) * code_lh
        ax = win_x + win_w - 220

        # Annotation background
        parts.append(rounded_rect(ax, ay - 16, 220, 36, ann_color, rx=6, opacity=0.2))
        parts.append(text(ax + 110, ay + 2, ann_text,
                          font_size=26, fill=ann_color, weight="600"))

    if title:
        parts.append(text(WIDTH / 2, HEIGHT - 12, title,
                          font_size=22, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts))


def _code_editor_split(cfg: dict) -> str:
    """Split-pane code editor (left: source, right: target)."""
    left_code = cfg.get("left_code", [])
    right_code = cfg.get("right_code", [])
    left_title = cfg.get("left_title", "Input")
    right_title = cfg.get("right_title", "Output")
    title = cfg.get("title", "")
    parts = []

    half_w = WIDTH / 2 - 20

    for side, code, side_title, offset_x in [
        ("left", left_code, left_title, 15),
        ("right", right_code, right_title, WIDTH / 2 + 5),
    ]:
        win_x = offset_x
        win_y = 30
        win_w = half_w
        win_h = HEIGHT - 60

        # Window
        parts.append(rounded_rect(win_x, win_y, win_w, win_h,
                                   Palette.BG_CODE, stroke=Palette.BORDER, stroke_width=1, rx=8))

        # Title bar
        parts.append(rounded_rect(win_x, win_y, win_w, 30, "#161b22", rx=8))
        parts.append(f'<rect x="{win_x}" y="{win_y + 16}" width="{win_w}" height="14" fill="#161b22"/>')

        # Traffic lights
        parts.append(circle(win_x + 16, win_y + 15, 5, "#ff5f57"))
        parts.append(circle(win_x + 32, win_y + 15, 5, "#febc2e"))
        parts.append(circle(win_x + 48, win_y + 15, 5, "#28c840"))

        # Side title
        color = Palette.BLUE if side == "left" else Palette.GREEN
        parts.append(text(win_x + win_w / 2, win_y + 15, side_title,
                          font_size=22, fill=color, weight="600",
                          font_family="'JetBrains Mono', monospace"))

        # Code
        code_x = win_x + 40
        code_y = win_y + 50
        parts.append(_render_code_lines(code_x, code_y, code,
                                        font_size=26, line_height=38,
                                        show_line_numbers=True))

    if title:
        parts.append(text(WIDTH / 2, HEIGHT - 10, title,
                          font_size=22, fill=Palette.TEXT_MUTED))

    return svg_doc("\n".join(parts))


def _db_table(cfg: dict) -> str:
    """Database table mockup with colored rows."""
    columns = cfg.get("columns", [])
    rows = cfg.get("rows", [])
    table_name = cfg.get("table_name", "table")
    title = cfg.get("title", "")
    parts = []

    if title:
        parts.append(text(WIDTH / 2, 30, title, font_size=40, weight="700"))

    n_cols = len(columns)
    n_rows = len(rows)

    tbl_x = 60
    tbl_y = 55
    tbl_w = WIDTH - 120
    col_w = tbl_w / max(n_cols, 1)
    row_h = (HEIGHT - 140) / max(n_rows + 1, 1)

    # Table background
    parts.append(rounded_rect(tbl_x, tbl_y, tbl_w, (n_rows + 1) * row_h + 10,
                               Palette.BG_CODE, stroke=Palette.BORDER, stroke_width=1, rx=8))

    # Table name badge
    parts.append(rounded_rect(tbl_x, tbl_y - 5, len(table_name) * 11 + 24, 26,
                               Palette.BLUE, rx=4))
    parts.append(text(tbl_x + len(table_name) * 5.5 + 12, tbl_y + 8, table_name,
                      font_size=22, weight="700", fill=Palette.TEXT_LIGHT,
                      font_family="'JetBrains Mono', monospace"))

    # Header row
    header_y = tbl_y + 15
    parts.append(f'<rect x="{tbl_x}" y="{header_y}" width="{tbl_w}" height="{row_h}" '
                 f'fill="{Palette.BG_CARD}" rx="0"/>')
    for j, col_name in enumerate(columns):
        cx_pos = tbl_x + j * col_w + col_w / 2
        parts.append(text(cx_pos, header_y + row_h / 2, col_name,
                          font_size=24, weight="700", fill=Palette.TEXT_LIGHT,
                          font_family="'JetBrains Mono', monospace"))

    # Separator line
    parts.append(line(tbl_x, header_y + row_h, tbl_x + tbl_w, header_y + row_h,
                      Palette.BORDER_LIGHT, 1))

    # Data rows
    for i, row in enumerate(rows):
        ry = header_y + row_h + i * row_h
        row_color = row.get("row_color", None) if isinstance(row, dict) else None
        cells = row.get("cells", row) if isinstance(row, dict) else row

        if row_color:
            parts.append(f'<rect x="{tbl_x}" y="{ry}" width="{tbl_w}" height="{row_h}" '
                         f'fill="{row_color}" opacity="0.1"/>')
        elif i % 2 == 1:
            parts.append(f'<rect x="{tbl_x}" y="{ry}" width="{tbl_w}" height="{row_h}" '
                         f'fill="{Palette.BG_CARD}" opacity="0.3"/>')

        for j, cell in enumerate(cells if isinstance(cells, list) else []):
            cx_pos = tbl_x + j * col_w + col_w / 2
            cell_color = Palette.TEXT_LIGHT
            if isinstance(cell, dict):
                cell_color = cell.get("color", cell_color)
                cell = cell.get("value", "")
            parts.append(text(cx_pos, ry + row_h / 2, str(cell),
                              font_size=22, fill=cell_color,
                              font_family="'JetBrains Mono', monospace"))

    return svg_doc("\n".join(parts))


def _multi_panel(cfg: dict) -> str:
    """Multi-panel dashboard layout."""
    panels = cfg.get("panels", [])
    title = cfg.get("title", "")
    layout = cfg.get("layout", "2x2")  # "2x2", "3x1", "1x3"
    parts = []

    title_h = 80 if title else 10
    if title:
        parts.append(text(WIDTH / 2, 42, title, font_size=52, weight="700"))

    # Parse layout
    if layout == "2x2":
        cols, rows_count = 2, 2
    elif layout == "3x1":
        cols, rows_count = 3, 1
    elif layout == "1x3":
        cols, rows_count = 1, 3
    else:
        cols, rows_count = 2, 2

    gap = 20
    margin = 40
    start_y = title_h
    avail_w = WIDTH - 2 * margin
    avail_h = HEIGHT - start_y - 20

    panel_w = (avail_w - (cols - 1) * gap) / cols
    panel_h = (avail_h - (rows_count - 1) * gap) / rows_count

    # Scale font and line spacing so content fills the panel
    title_bar_h = 48
    content_pad_top = 20
    content_pad_bottom = 16
    content_pad_left = 28
    max_lines = max((len(p.get("content", [])) for p in panels), default=1) or 1
    content_area_h = panel_h - title_bar_h - content_pad_top - content_pad_bottom
    line_h = min(58, content_area_h / max_lines)
    font_sz = min(38, int(line_h * 0.72))

    # Horizontal cap: ensure longest line fits in panel width
    longest_chars = max(
        (max((len(cl) for cl in p.get("content", [""])), default=1)
         for p in panels), default=10)
    max_font_by_w = int((panel_w - 2 * content_pad_left) / max(longest_chars * 0.62, 1))
    font_sz = max(18, min(font_sz, max_font_by_w))
    line_h = max(line_h, font_sz * 1.35)

    colors = [Palette.BLUE, Palette.GREEN, Palette.PURPLE, Palette.TEAL]

    for i, panel in enumerate(panels):
        col = i % cols
        row = i // cols
        if row >= rows_count:
            break

        px = margin + col * (panel_w + gap)
        py = start_y + row * (panel_h + gap)
        accent = panel.get("color", colors[i % len(colors)])

        # Panel background
        parts.append(rounded_rect(px, py, panel_w, panel_h,
                                   Palette.BG_CODE, stroke=Palette.BORDER,
                                   stroke_width=1, rx=10))

        # Panel title bar
        parts.append(f'<rect x="{px}" y="{py}" width="{panel_w}" '
                     f'height="{title_bar_h}" rx="10" '
                     f'fill="{accent}" opacity="0.2"/>')
        parts.append(text(px + panel_w / 2, py + title_bar_h / 2,
                          panel.get("title", f"Panel {i + 1}"),
                          font_size=32, weight="700", fill=accent))

        # Panel content — left-aligned monospace, vertically centered
        content_lines = panel.get("content", [])
        n_lines = len(content_lines) or 1
        content_block_h = n_lines * line_h
        content_area_top = py + title_bar_h
        content_area_bot = py + panel_h - content_pad_bottom
        content_area_mid = (content_area_top + content_area_bot) / 2
        content_start_y = content_area_mid - content_block_h / 2 + line_h / 2
        for j, cl in enumerate(content_lines):
            parts.append(text(px + content_pad_left, content_start_y + j * line_h,
                              cl, font_size=font_sz, fill=Palette.TEXT_MUTED,
                              font_family="'JetBrains Mono', monospace",
                              anchor="start"))

    return svg_doc("\n".join(parts))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

CODE_TEMPLATES = {
    "code_editor": _code_editor,
    "code_editor_split": _code_editor_split,
    "db_table": _db_table,
    "multi_panel": _multi_panel,
}


def render_code_block(template: str, cfg: dict) -> str:
    """Render a code/screenshot SVG from template name and config."""
    fn = CODE_TEMPLATES.get(template)
    if not fn:
        raise ValueError(f"Unknown code template: {template}. "
                         f"Available: {list(CODE_TEMPLATES.keys())}")
    return fn(cfg)
