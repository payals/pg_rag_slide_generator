"""
Renderer module for generating reveal.js presentations from slide data.

Reads slides from Postgres, injects static content (title, thanks, section dividers),
formats speaker notes with citations, and exports a self-contained HTML file.
"""

import argparse
import asyncio
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID

from jinja2 import Environment, FileSystemLoader, DictLoader, ChoiceLoader

from src.content_utils import walk_content_data, init_content_field_map
from src.models import get_slide_type

from src.db import get_connection

import src.models as _models
from src.models import (
    load_intent_type_map,
    load_static_slides,
    load_section_dividers,
    load_themes,
    load_slide_type_configs,
    load_prompt_templates,
)


# -----------------------------------------------------------------------------
# Renderer initialization (replaces hardcoded constants)
# -----------------------------------------------------------------------------

_initialized = False


async def init_renderer():
    """Load all renderer configuration from Postgres.

    Must be called once before rendering. Populates the module-level
    caches in src/models.py that replace the former hardcoded constants.
    Safe to call multiple times (idempotent).
    """
    global _initialized
    if _initialized:
        return
    await load_intent_type_map()
    await load_static_slides()
    await load_section_dividers()
    await load_themes()
    await load_slide_type_configs()
    init_content_field_map(_models.SLIDE_TYPE_CONFIGS)
    _init_fragment_composition()
    await load_prompt_templates()
    _initialized = True


def _check_initialized():
    """Raise RuntimeError if init_renderer() hasn't been called."""
    if not _initialized:
        raise RuntimeError(
            "Renderer not initialized. Call await init_renderer() first."
        )


def get_intent_order() -> list[str]:
    """Return ordered list of all intents (title through thanks).

    Derived from INTENT_TYPE_MAP sorted by sort_order.
    Replaces the former INTENT_ORDER constant.
    """
    _check_initialized()
    return [
        intent for intent, _ in sorted(
            _models.INTENT_TYPE_MAP.items(), key=lambda x: x[1].sort_order
        )
    ]


def get_target_slides() -> int:
    """Return count of generatable intents (excludes title/thanks).

    Replaces the former TARGET_SLIDES constant.
    """
    _check_initialized()
    return len([
        i for i, info in _models.INTENT_TYPE_MAP.items() if info.is_generatable
    ])


def get_title_slide() -> dict:
    """Return title slide data from DB cache.

    Replaces the former TITLE_SLIDE constant.
    """
    _check_initialized()
    return _models.STATIC_SLIDES["title"]


def get_thanks_slide() -> dict:
    """Return thanks slide data from DB cache.

    Replaces the former THANKS_SLIDE constant.
    """
    _check_initialized()
    return _models.STATIC_SLIDES["thanks"]


def get_section_dividers() -> list[tuple[str, str]]:
    """Return section dividers as (after_intent, title) tuples.

    Replaces the former SECTION_DIVIDERS constant.
    Format matches the old constant for backward compatibility.
    """
    _check_initialized()
    return [(d["after_intent"], d["title"]) for d in _models.SECTION_DIVIDERS_CACHE]


def get_divider_images() -> dict[str, str]:
    """Return mapping of divider title to image filename.

    Replaces the former DIVIDER_IMAGES constant.
    """
    _check_initialized()
    return {
        d["title"]: d["image_filename"]
        for d in _models.SECTION_DIVIDERS_CACHE
        if d.get("image_filename")
    }


def get_themes() -> dict[str, dict]:
    """Return theme configurations from DB cache.

    Replaces the former THEMES constant.
    The returned dict maps theme name to {"name": display_name, "overrides": css_overrides}.
    """
    _check_initialized()
    return {
        name: {
            "name": data["display_name"],
            "overrides": data["css_overrides"],
        }
        for name, data in _models.THEMES_CACHE.items()
    }


# -----------------------------------------------------------------------------
# Fragment Composition Engine
# -----------------------------------------------------------------------------

def _derive_fragment_order() -> list[str]:
    """Return non-bullets slide types from DB-loaded SLIDE_TYPE_CONFIGS.

    Falls back to a hardcoded list if configs haven't been loaded yet.
    """
    if _models.SLIDE_TYPE_CONFIGS:
        return [st for st in sorted(_models.SLIDE_TYPE_CONFIGS) if st != "bullets"]
    return ["code", "diagram", "flow", "split", "statement"]


def compose_slide_type_body(fragments: dict[str, str]) -> str | None:
    """Compose per-type HTML fragments into a complete _slide_type_body.html template.

    Args:
        fragments: Dict mapping slide_type -> html_fragment string.
                   All values must be non-None for composition to proceed.

    Returns:
        Complete Jinja2 template string, or None if any fragment is missing/None.
    """
    if not fragments:
        return None
    fragment_order = _derive_fragment_order()
    for stype in fragment_order:
        if stype not in fragments or fragments[stype] is None:
            return None
    if "bullets" not in fragments or fragments["bullets"] is None:
        return None

    parts: list[str] = []

    for i, stype in enumerate(fragment_order):
        keyword = "if" if i == 0 else "elif"
        parts.append(
            f"{{% {keyword} slide.slide_type == '{stype}' and slide.content_data %}}"
        )
        parts.append(fragments[stype])
        parts.append("")

    parts.append("{% else %}")
    parts.append(
        "{# Default: bullets (existing layout, also fallback for missing content_data) #}"
    )
    parts.append(fragments["bullets"])
    parts.append("{% endif %}")
    parts.append("")
    parts.append("{% if slide.image_path %}")
    parts.append('<div class="slide-image">')
    parts.append(
        '    <img src="{{ slide.image_path }}" alt="{{ slide.image_alt | default(\'Slide image\') }}">'
    )
    parts.append("</div>")
    parts.append("{% endif %}")

    return "\n".join(parts)


_COMPOSED_SLIDE_TYPE_BODY: str | None = None


def _init_fragment_composition() -> None:
    """Compose DB fragments into a template string and cache it.

    Called during init_renderer() after load_slide_type_configs().
    If composition fails (fragments missing/NULL), _COMPOSED_SLIDE_TYPE_BODY
    stays None and the filesystem fallback is used.
    """
    global _COMPOSED_SLIDE_TYPE_BODY
    fragments = {
        stype: config.get("html_fragment")
        for stype, config in _models.SLIDE_TYPE_CONFIGS.items()
    }
    _COMPOSED_SLIDE_TYPE_BODY = compose_slide_type_body(fragments)


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Template directory relative to this file
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

# Output directory
OUTPUT_DIR = Path(__file__).parent.parent / "output"


# -----------------------------------------------------------------------------
# Data Classes
# -----------------------------------------------------------------------------

@dataclass
class RenderedSlide:
    """A slide ready for rendering."""
    slide_no: int
    intent: str
    title: str
    bullets: list[str]
    speaker_notes: Optional[str]
    citations: list[dict]
    is_static: bool = False
    is_divider: bool = False
    is_title: bool = False
    is_thanks: bool = False
    subtitle: Optional[str] = None
    speaker: Optional[str] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    company_url: Optional[str] = None
    event: Optional[str] = None
    image_path: Optional[str] = None
    image_alt: Optional[str] = None
    slide_type: str = "bullets"
    content_data: Optional[dict] = None


_CITATION_HASH_RE = re.compile(
    r"\s*\["
    r"[0-9a-f]{8}(?:-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?"
    r"(?:\s*,\s*[0-9a-f]{8}(?:-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?)*"
    r"\]"
)


def _strip_hash(text: str) -> str:
    return _CITATION_HASH_RE.sub("", text).rstrip()


def _strip_citation_hashes(bullets: list[str]) -> list[str]:
    """Remove inline citation hashes like [7145eea4] from bullet text."""
    return [_strip_hash(b) for b in bullets]


def _strip_content_data_hashes(cd: dict) -> dict:
    """Strip citation hashes from all visible text fields in content_data."""
    return walk_content_data(cd, _strip_hash)


# -----------------------------------------------------------------------------
# Database Functions
# -----------------------------------------------------------------------------

async def load_slides(deck_id: UUID) -> list[dict]:
    """
    Load all slides for a deck from the database.
    
    Uses LEFT JOIN to include image data when available.
    
    Args:
        deck_id: UUID of the deck to load
        
    Returns:
        List of slide dictionaries ordered by slide_no
    """
    async with get_connection() as conn:
        rows = await conn.fetch("""
            SELECT 
                s.slide_id,
                s.slide_no,
                s.intent::text as intent,
                s.title,
                s.bullets,
                s.speaker_notes,
                s.citations,
                s.slide_type::text as slide_type,
                s.content_data,
                s.retry_count,
                s.created_at,
                ia.storage_path as image_path,
                ia.alt_text as image_alt
            FROM slide s
            LEFT JOIN image_asset ia ON s.image_id = ia.image_id
            WHERE s.deck_id = $1
            ORDER BY s.slide_no
        """, deck_id)
        
        return [dict(row) for row in rows]


async def get_deck_info(deck_id: UUID) -> Optional[dict]:
    """
    Get deck metadata.
    
    Args:
        deck_id: UUID of the deck
        
    Returns:
        Deck metadata dict or None if not found
    """
    async with get_connection() as conn:
        row = await conn.fetchrow("""
            SELECT deck_id, topic, description, target_slides, created_at
            FROM deck
            WHERE deck_id = $1
        """, deck_id)
        
        return dict(row) if row else None


# -----------------------------------------------------------------------------
# Slide Processing
# -----------------------------------------------------------------------------

def inject_static_slides(slides: list[dict]) -> list[RenderedSlide]:
    """
    Inject static slides (title, thanks) and section dividers into the slide list.
    
    The function:
    1. Converts database slides to RenderedSlide objects
    2. Adds the title slide at the beginning
    3. Inserts section dividers at appropriate positions
    4. Adds the thanks slide at the end
    5. Renumbers all slides sequentially
    
    Args:
        slides: List of slide dicts from database
        
    Returns:
        List of RenderedSlide objects with static content injected
    """
    title_slide = get_title_slide()
    thanks_slide = get_thanks_slide()
    dividers_after = {intent: title for intent, title in get_section_dividers()}
    divider_images = get_divider_images()
    intent_order = get_intent_order()

    result = []
    
    # Add title slide first
    result.append(RenderedSlide(
        slide_no=1,
        intent="title",
        title=title_slide["title"],
        bullets=[],
        speaker_notes="Welcome everyone! Today we're going to explore how Postgres can serve as a complete AI control plane.",
        citations=[],
        is_static=True,
        is_title=True,
        subtitle=title_slide["subtitle"],
        speaker=title_slide["speaker"],
        job_title=title_slide.get("job_title"),
        company=title_slide.get("company"),
        company_url=title_slide.get("company_url"),
        event=title_slide["event"],
    ))
    
    # Create intent -> slide mapping
    slides_by_intent = {s["intent"]: s for s in slides}
    
    # Process intents in order
    for intent in intent_order:
        # Skip static intents - we handle them separately
        if intent in ("title", "thanks"):
            continue
            
        # Add the slide if it was generated by the LLM
        if intent in slides_by_intent:
            slide = slides_by_intent[intent]
            
            # Parse bullets from JSONB
            bullets = slide.get("bullets", [])
            if isinstance(bullets, str):
                import json
                bullets = json.loads(bullets)
            bullets = _strip_citation_hashes(bullets)
            
            # Parse citations from JSONB
            citations = slide.get("citations", [])
            if isinstance(citations, str):
                import json
                citations = json.loads(citations)
            
            # Normalize citation keys: ensure 'title' exists for renderer
            for citation in (citations or []):
                if 'doc_title' in citation and 'title' not in citation:
                    citation['title'] = citation['doc_title']
            
            slide_type = slide.get("slide_type") or get_slide_type(intent)
            content_data = slide.get("content_data") or {}
            if isinstance(content_data, str):
                import json
                content_data = json.loads(content_data)
            content_data = _strip_content_data_hashes(content_data)

            notes = slide.get("speaker_notes")
            if notes:
                notes = _strip_hash(notes)

            result.append(RenderedSlide(
                slide_no=len(result) + 1,
                intent=intent,
                title=slide["title"],
                bullets=bullets if bullets else [],
                speaker_notes=notes,
                citations=citations if citations else [],
                image_path=slide.get("image_path"),
                image_alt=slide.get("image_alt"),
                slide_type=slide_type,
                content_data=content_data if content_data else None,
            ))

        elif intent in _models.STATIC_SLIDES:
            static = _models.STATIC_SLIDES[intent]
            result.append(RenderedSlide(
                slide_no=len(result) + 1,
                intent=intent,
                title=static["title"],
                bullets=static.get("bullets", []),
                speaker_notes=static.get("speaker_notes"),
                citations=[],
                is_static=True,
                image_path=static.get("image_path") or None,
                image_alt=static.get("image_alt") or None,
                slide_type=static.get("slide_type", "bullets"),
                content_data=static.get("content_data") or None,
            ))
        
        # Insert divider after this intent if needed
        if intent in dividers_after:
            divider_title = dividers_after[intent]
            divider_image = divider_images.get(divider_title)
            result.append(RenderedSlide(
                slide_no=len(result) + 1,
                intent="divider",
                title=divider_title,
                bullets=[],
                speaker_notes=f"Transition to next section: {divider_title}",
                citations=[],
                is_static=True,
                is_divider=True,
                image_path=divider_image,
                image_alt=f"Section: {divider_title}" if divider_image else None,
            ))
    
    # Add thanks slide at the end
    result.append(RenderedSlide(
        slide_no=len(result) + 1,
        intent="thanks",
        title=thanks_slide["title"],
        bullets=thanks_slide["bullets"],
        speaker_notes=thanks_slide["speaker_notes"],
        citations=[],
        is_static=True,
        is_thanks=True,
    ))
    
    # Renumber all slides sequentially
    for i, slide in enumerate(result, start=1):
        slide.slide_no = i
    
    return result


def format_speaker_notes(slide: RenderedSlide) -> str:
    """
    Format speaker notes for a slide with citations.
    
    Speaker notes format:
    - Main explanation/talking points
    - Key terms to mention
    - Citations with source titles
    
    Args:
        slide: RenderedSlide object
        
    Returns:
        Formatted speaker notes HTML string
    """
    parts = []
    
    # Add main notes
    if slide.speaker_notes:
        parts.append(slide.speaker_notes)
    
    # Add citations if present
    if slide.citations:
        parts.append("\n\nSources:")
        for i, citation in enumerate(slide.citations, start=1):
            # Handle both LLM output format (doc_title) and schema format (title)
            title = citation.get("doc_title") or citation.get("title") or "Unknown Source"
            url = citation.get("url", "")
            if url:
                parts.append(f"  [{i}] {title} ({url})")
            else:
                parts.append(f"  [{i}] {title}")
    
    return "\n".join(parts)


def render_slide(slide: RenderedSlide) -> dict:
    """
    Prepare a slide for Jinja2 template rendering.
    
    Args:
        slide: RenderedSlide object
        
    Returns:
        Dict with template-ready data
    """
    return {
        "slide_no": slide.slide_no,
        "intent": slide.intent,
        "title": slide.title,
        "subtitle": slide.subtitle,
        "speaker": slide.speaker,
        "job_title": slide.job_title,
        "company": slide.company,
        "company_url": slide.company_url,
        "event": slide.event,
        "bullets": slide.bullets,
        "speaker_notes": format_speaker_notes(slide),
        "is_title": slide.is_title,
        "is_thanks": slide.is_thanks,
        "is_divider": slide.is_divider,
        "image_path": slide.image_path,
        "image_alt": slide.image_alt,
        "slide_type": slide.slide_type,
        "content_data": slide.content_data or {},
    }


# -----------------------------------------------------------------------------
# HTML Rendering
# -----------------------------------------------------------------------------

def get_jinja_env() -> Environment:
    """Get configured Jinja2 environment.

    Uses a ChoiceLoader: if DB-composed fragments are available, they
    override _slide_type_body.html from the filesystem. All other
    templates (slide_fragment.html, reveal_base.html) load from disk.
    """
    loaders: list = []
    if _COMPOSED_SLIDE_TYPE_BODY is not None:
        loaders.append(DictLoader({"_slide_type_body.html": _COMPOSED_SLIDE_TYPE_BODY}))
    loaders.append(FileSystemLoader(str(TEMPLATE_DIR)))
    return Environment(
        loader=ChoiceLoader(loaders),
        autoescape=True,
    )


async def render_deck(deck_id: UUID, output_dir: Optional[Path] = None, theme: str = "dark") -> str:
    """
    Render a complete deck to HTML.
    
    Loads slides from database, injects static content,
    copies images to output/images/, and renders to a reveal.js HTML presentation.
    
    Args:
        deck_id: UUID of the deck to render
        output_dir: Output directory (default: OUTPUT_DIR)
        theme: Theme name ('dark' or 'postgres')
        
    Returns:
        Complete HTML string for the presentation
    """
    output_dir = output_dir or OUTPUT_DIR
    
    # Load deck info
    deck_info = await get_deck_info(deck_id)
    if not deck_info:
        raise ValueError(f"Deck not found: {deck_id}")
    
    # Load slides from database
    db_slides = await load_slides(deck_id)
    
    # Inject static slides and dividers
    all_slides = inject_static_slides(db_slides)
    
    # Copy images to output/images/ and update paths
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    
    for slide in all_slides:
        if slide.image_path:
            src = Path("content/images") / slide.image_path
            if src.exists():
                dst = images_dir / Path(slide.image_path).name
                shutil.copy2(src, dst)
                mtime = int(src.stat().st_mtime)
                slide.image_path = f"images/{Path(slide.image_path).name}?v={mtime}"
            else:
                slide.image_path = None
                slide.image_alt = None

    # Copy logo to output/images/
    logo_src = Path("content/images/netapp_logo.png")
    if logo_src.exists():
        shutil.copy2(logo_src, images_dir / "netapp_logo.png")
    
    # Prepare slides for template
    template_slides = [render_slide(s) for s in all_slides]
    
    # Render template
    env = get_jinja_env()
    template = env.get_template("reveal_base.html")
    
    # Get theme overrides
    themes = get_themes()
    theme_config = themes.get(theme, themes["dark"])
    
    html = template.render(
        title=deck_info["topic"],
        slides=template_slides,
        deck_id=str(deck_id),
        generated_at=deck_info.get("created_at", ""),
        theme_overrides=theme_config["overrides"],
        title_slide=get_title_slide(),
    )
    
    return html


def render_single_slide_html(
    slide_dict: dict,
    sent_dividers: set,
    image_url_prefix: str = "/images",
) -> tuple:
    """
    Render a single slide (+ any preceding divider) as HTML fragment(s).
    
    Builds a RenderedSlide from the slide dict, checks which divider(s)
    should precede this slide, rewrites image paths, and renders via
    the slide_fragment.html template.
    
    Args:
        slide_dict: Slide row from DB (intent, title, bullets, etc.)
        sent_dividers: Set of divider titles already sent (mutated in place)
        image_url_prefix: URL prefix for images (default: /images for live server)
        
    Returns:
        Tuple of (html_string, updated_sent_dividers)
    """
    import json as _json
    
    intent = slide_dict.get("intent", "")
    
    # Parse bullets
    bullets = slide_dict.get("bullets", [])
    if isinstance(bullets, str):
        bullets = _json.loads(bullets)
    bullets = _strip_citation_hashes(bullets)
    
    # Parse citations
    citations = slide_dict.get("citations", [])
    if isinstance(citations, str):
        citations = _json.loads(citations)
    
    # Normalize citation keys
    for citation in (citations or []):
        if 'doc_title' in citation and 'title' not in citation:
            citation['title'] = citation['doc_title']
    
    # Rewrite image path for live server (with cache-busting mtime param)
    image_path = slide_dict.get("image_path") or slide_dict.get("storage_path")
    if image_path:
        from pathlib import Path as _Path
        filename = _Path(image_path).name
        src_file = _Path("content/images") / filename
        if src_file.exists():
            mtime = int(src_file.stat().st_mtime)
            image_path = f"{image_url_prefix}/{filename}?v={mtime}"
        else:
            image_path = None
    
    # Parse content_data
    content_data = slide_dict.get("content_data") or {}
    if isinstance(content_data, str):
        content_data = _json.loads(content_data)
    content_data = _strip_content_data_hashes(content_data)

    notes = slide_dict.get("speaker_notes")
    if notes:
        notes = _strip_hash(notes)

    slide = RenderedSlide(
        slide_no=slide_dict.get("slide_no", 0),
        intent=intent,
        title=slide_dict.get("title", ""),
        bullets=bullets if bullets else [],
        speaker_notes=notes,
        citations=citations if citations else [],
        image_path=image_path,
        image_alt=slide_dict.get("image_alt"),
        slide_type=slide_dict.get("slide_type", "bullets"),
        content_data=content_data if content_data else None,
    )
    
    # Determine which dividers should precede this slide
    intent_order = get_intent_order()
    dividers_after = {trigger: title for trigger, title in get_section_dividers()}
    divider_images = get_divider_images()

    slides_for_template = []
    
    try:
        current_idx = intent_order.index(intent)
    except ValueError:
        current_idx = -1
    
    if current_idx >= 0:
        for i, order_intent in enumerate(intent_order):
            if i >= current_idx:
                break
            if order_intent in dividers_after:
                divider_title = dividers_after[order_intent]
                if divider_title not in sent_dividers:
                    divider_image = divider_images.get(divider_title)
                    if divider_image:
                        divider_image = f"{image_url_prefix}/{divider_image}"
                    divider_slide = render_slide(RenderedSlide(
                        slide_no=0,
                        intent="divider",
                        title=divider_title,
                        bullets=[],
                        speaker_notes=f"Transition to next section: {divider_title}",
                        citations=[],
                        is_static=True,
                        is_divider=True,
                        image_path=divider_image,
                        image_alt=f"Section: {divider_title}" if divider_image else None,
                    ))
                    slides_for_template.append(divider_slide)
                    sent_dividers.add(divider_title)

            if order_intent in _models.STATIC_SLIDES and order_intent not in ("title", "thanks"):
                static_key = f"static:{order_intent}"
                if static_key not in sent_dividers:
                    static = _models.STATIC_SLIDES[order_intent]
                    static_img = static.get("image_path") or None
                    if static_img:
                        from pathlib import Path as _Path
                        src_file = _Path("content/images") / static_img
                        if src_file.exists():
                            mtime = int(src_file.stat().st_mtime)
                            static_img = f"{image_url_prefix}/{static_img}?v={mtime}"
                        else:
                            static_img = None
                    static_slide = render_slide(RenderedSlide(
                        slide_no=0,
                        intent=order_intent,
                        title=static["title"],
                        bullets=static.get("bullets", []),
                        speaker_notes=static.get("speaker_notes"),
                        citations=[],
                        is_static=True,
                        image_path=static_img,
                        image_alt=static.get("image_alt") or None,
                        slide_type=static.get("slide_type", "bullets"),
                        content_data=static.get("content_data") or None,
                    ))
                    slides_for_template.append(static_slide)
                    sent_dividers.add(static_key)
    
    # Add the actual slide
    slides_for_template.append(render_slide(slide))
    
    # Render via fragment template
    env = get_jinja_env()
    template = env.get_template("slide_fragment.html")
    html = template.render(slides=slides_for_template)
    
    return (html, sent_dividers)


def render_deck_from_slides(slides: list[dict], title: str = "Presentation", theme: str = "dark") -> str:
    """
    Render a deck from a list of slide dicts (for testing without database).
    
    Args:
        slides: List of slide dicts with intent, title, bullets, etc.
        title: Presentation title
        theme: Theme name ('dark' or 'postgres')
        
    Returns:
        Complete HTML string
    """
    _check_initialized()

    # Inject static slides
    all_slides = inject_static_slides(slides)
    
    # Prepare slides for template
    template_slides = [render_slide(s) for s in all_slides]
    
    # Get theme overrides
    themes = get_themes()
    theme_config = themes.get(theme, themes["dark"])
    
    # Render template
    env = get_jinja_env()
    template = env.get_template("reveal_base.html")
    
    html = template.render(
        title=title,
        slides=template_slides,
        deck_id="test-deck",
        generated_at="",
        theme_overrides=theme_config["overrides"],
        title_slide=get_title_slide(),
    )
    
    return html


def export_html(html: str, output_path: Path) -> Path:
    """
    Export HTML to a file.
    
    Creates output directory if it doesn't exist.
    
    Args:
        html: HTML content to write
        output_path: Path to output file
        
    Returns:
        Path to the written file
    """
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write file
    output_path.write_text(html, encoding="utf-8")
    
    return output_path


def make_deck_filename(topic: str, timestamp: Optional[datetime] = None) -> str:
    """
    Build a deck filename from a topic and timestamp.
    
    Format: <YYYYMMDD>_<HHMMSS>_<slugified_topic>.html
    
    The topic is lowercased, non-alphanumeric characters are replaced
    with underscores, and consecutive/trailing underscores are collapsed.
    
    Args:
        topic: Deck topic string (e.g. "Postgres as AI Application Server")
        timestamp: Optional datetime; defaults to now (UTC)
        
    Returns:
        Filename string, e.g. "20260208_143052_postgres_as_ai_application_server.html"
    """
    ts = timestamp or datetime.utcnow()
    date_str = ts.strftime("%Y%m%d_%H%M%S")
    # Slugify: lowercase, replace non-alphanum with underscore, collapse runs
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    return f"{date_str}_{slug}.html"


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def save_fallback(html: str) -> Path:
    """
    Save a rendered deck as the fallback deck.
    
    Copies to output/fallback_deck.html for use when generation fails.
    
    Args:
        html: HTML content of the deck
        
    Returns:
        Path to the fallback deck file
    """
    fallback_path = OUTPUT_DIR / "fallback_deck.html"
    return export_html(html, fallback_path)


async def main():
    """CLI entry point for rendering a deck."""
    from src.db import init_pool
    from src import config
    await init_pool()
    await config.init_config()
    await init_renderer()

    themes = get_themes()
    parser = argparse.ArgumentParser(
        description="Render slides from Postgres to reveal.js HTML"
    )
    parser.add_argument(
        "--deck-id",
        type=str,
        required=True,
        help="UUID of the deck to render"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: output/<date>_<time>_<topic>.html)"
    )
    parser.add_argument(
        "--save-fallback",
        action="store_true",
        help="Also save as output/fallback_deck.html for fallback use"
    )
    parser.add_argument(
        "--theme",
        type=str,
        choices=list(themes.keys()),
        default="dark",
        help=f"Theme to apply (choices: {', '.join(themes.keys())}; default: dark)"
    )
    
    args = parser.parse_args()
    
    try:
        deck_id = UUID(args.deck_id)
    except ValueError:
        print(f"Error: Invalid deck ID: {args.deck_id}")
        return 1
    
    if args.output:
        output_path = Path(args.output)
    else:
        # Look up topic from DB for the filename
        deck_info = await get_deck_info(deck_id)
        topic = (deck_info or {}).get("topic", str(deck_id)[:8])
        output_path = OUTPUT_DIR / make_deck_filename(topic)
    
    print(f"Rendering deck {deck_id}...")
    
    try:
        html = await render_deck(deck_id, theme=args.theme)
        export_html(html, output_path)
        print(f"✓ Deck rendered to {output_path} (theme: {args.theme})")
        
        if args.save_fallback:
            fb_path = save_fallback(html)
            print(f"✓ Fallback deck saved to {fb_path}")
        
        print(f"  Open in browser to view, press 'S' for speaker notes")
        return 0
    except Exception as e:
        print(f"Error rendering deck: {e}")
        return 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
