"""
Raw LLM Slide Deck Generator — no Postgres control plane.

Generates a reveal.js slide deck by asking the LLM to produce all slide
content in a single call.  Uses a stock reveal.js template (CDN + default
theme) — no custom slide-type layouts, no image pipeline, no quality gates.

Reads OPENAI_API_KEY (and optional OPENAI_API_BASE, OPENAI_USER, SSL_VERIFY)
from .env or the shell environment — no secrets are hardcoded.

Purpose:
  Produce a "baseline" deck to compare against the Postgres-controlled
  deck, demonstrating what the control plane adds: custom template,
  curated images, RAG grounding, quality gates, slide-type layouts.

Usage:
  python scripts/generate_raw_llm_deck.py --topic "Postgres as AI Control Plane"
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader
from openai import AsyncOpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

# Load .env early so all os.getenv() calls see the values
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
TEMPLATE_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "output"

TITLE_SLIDE = {
    "title": "Postgres as AI Control Plane",
    "subtitle": "How one database can orchestrate your entire AI pipeline",
    "speaker": "Payal Singh",
    "job_title": "DBRE",
    "company": "NetApp",
    "company_url": "https://www.netapp.com",
    "event": "SCaLE 23x — March 2026",
}

THANKS_SLIDE = {
    "title": "Thank You!",
    "bullets": [
        "Questions?",
        "GitHub: github.com/payalsingh/scale23x-demo",
        "Slides generated with raw LLM — no control plane",
    ],
    "speaker_notes": "Thank you for attending!  Happy to take questions.",
}


# ─────────────────────────────────────────────────────────────────────
# LLM Client
# ─────────────────────────────────────────────────────────────────────

async def get_client() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    base_url = os.getenv("OPENAI_API_BASE")
    ssl_verify = os.getenv("SSL_VERIFY", "true").lower() != "false"
    http_client = None if ssl_verify else httpx.AsyncClient(verify=False)

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    if http_client:
        kwargs["http_client"] = http_client
    return AsyncOpenAI(**kwargs)


# ─────────────────────────────────────────────────────────────────────
# Deck generation prompts
# ─────────────────────────────────────────────────────────────────────

def build_minimal_prompt(topic: str) -> str:
    """Bare-minimum prompt: topic, audience, slide count, JSON format.

    No content plan, no quality guidance, no styling hints.
    This is what you get when the control plane does nothing for you.
    """
    return f"""\
Generate a 16-slide technical presentation about "{topic}" \
for SCaLE 23x (Southern California Linux Expo).
Audience: developers, DBAs, platform engineers.

Return as a JSON object with:
{{"theme": {{"bg_color": "...", "text_color": "...", "accent_color": "...", "font": "..."}}, \
"slides": [{{"title": "...", "bullets": [...], "speaker_notes": "...", "bg_color": "..."}}]}}
Return ONLY the JSON, no markdown fences."""


def build_guided_prompt(topic: str) -> str:
    """Detailed prompt with per-slide content plan, quality guidance, and styling.

    This gives the LLM the kind of structure the control plane normally provides:
    content planning (orchestrator), quality rules (gates), and formatting hints (schema).
    """
    return f"""\
Generate a 15-slide technical presentation about "{topic}" \
for SCaLE 23x (Southern California Linux Expo).
Audience: developers, DBAs, platform engineers.

Here's what I want for each slide:

Slide 1: Why do we need a control plane for LLMs?  \
explain how RAG stacks are a mess. Generate an actual inline <svg> diagram \
for the left side of the slide showing how messy a typical modern AI/RAG stack looks — embed the \
full SVG markup directly. On the right will be the bullets. Space them well.

Slide 2: Make the case for Postgres as the control plane. \
Why should one choose postgres? What features does it provide? etc. 

Slide 3: Why not a dedicated vector DB? \
explain benefits of postgres over other specialized vector DBs.

Slide 4: What can you do when Postgres is the brain? \
What kind of RAG functionalities are in pg? The highlights.

Slide 5: One bold statement capturing the big idea of using Postgres as control plane \
Something punchy and attention-grabbing and memorable. 

Slide 6: How Postgres features help you implement the control plane? \
and provide security that ad-hoc Python pipelines can't. \

Slide 7: High-level architecture showing how all \
the pieces fit together. Generate an actual inline <svg> diagram as one of \
the bullets showing the main components and data flow — embed the full SVG \
markup directly.

Slide 8: Quick explainer of what RAG is. \
Generate an actual inline <svg> diagram showing the \
basic RAG loop in postgres and python. 

Slide 9: Show real SQL for doing RAG entirely within \
Postgres. Actual code, not pseudocode. It should be in a code block that renders nicely in reveal.js

Slide 10: show the two stage RAG retrieval process - two columns - Left hadn side \
for the first stage (RRF) that happens in postgres, right hand side for the second stage (Cross-encoder reranker) \
that happens in python. \
Explain the two stages and the benefits of each.

Slide 11: Explain what MCP is. \
Generate an actual inline <svg> \
diagram as one of the bullets showing how MCP sits between components.

Slide 12: Real code examples of MCP tool definitions \
how to use MCP with postgres as the control plane?

Slide 13: The validation pipeline: show how the validation is done, what gates, what probes, etc.

Slide 14: How you monitor and debug the system. Show real \
SQL queries in a code block the various structures in postgres that help with observability. \
Do not hallucinate.

Slide 15: explain how we used this system to build the very slides you're watching. 
Mind-blown moment. bring the wow factor.

Slide 16: Key lessons, overview of our architecture and what the audience should go try.

For the overall deck theme: use a dark background like postgres blue \
, light text, and an accent color for highlights. Each slide \
should include a "bg_color" field if you want a specific background for that \
slide. Also suggest a "theme" object at the top level with font choices, \
accent color, and any overall styling notes. Title the slides appropriately. Don't repeat stuff \
Make slides split view for comparisons where relevant. \
Add svg diagrams where relevant (not too large). \
Add code blocks where relevant. \
Space the bullets and indent it well. \
Don't overcrowd the slides. \
Don't try to put in too much info. \
3-4 bullets per slide is enough. \
Add inline <svg> images and code blocks to make slides more interesting.

Return as a JSON object with:
{{"theme": {{"bg_color": "...", "text_color": "...", "accent_color": "...", "font": "..."}}, \
"slides": [{{"title": "...", "bullets": [...], "speaker_notes": "...", "bg_color": "..."}}]}}
Return ONLY the JSON, no markdown fences."""


# ─────────────────────────────────────────────────────────────────────
# Generation
# ─────────────────────────────────────────────────────────────────────

async def generate_slides(topic: str, minimal: bool = False) -> tuple[dict, list[dict]]:
    """Call the LLM once to generate all slides.

    Returns (theme_dict, slides_list).
    """
    client = await get_client()
    model = os.getenv("OPENAI_MODEL", "gpt-5")
    user = os.getenv("OPENAI_USER")

    prompt_type = "minimal" if minimal else "guided"
    prompt = build_minimal_prompt(topic) if minimal else build_guided_prompt(topic)
    logger.info(f"Generating slides about '{topic}' with {model} ({prompt_type} prompt)...")

    kwargs = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 16000,
    }
    if user:
        kwargs["user"] = user

    response = await client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    raw = (choice.message.content or "").strip()
    usage = response.usage
    logger.info(
        f"LLM response: {len(raw)} chars, "
        f"tokens: {usage.prompt_tokens}+{usage.completion_tokens}, "
        f"finish_reason: {choice.finish_reason}"
    )

    if choice.finish_reason == "length":
        logger.warning("Response was truncated (hit max_tokens). Output may be incomplete.")

    if not raw:
        logger.error("LLM returned empty response")
        sys.exit(1)

    text = raw
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    logger.info("Parsing JSON response...")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse LLM response as JSON: {exc}")
        logger.error(f"Raw response (first 2000 chars):\n{raw[:2000]}")
        sys.exit(1)
    logger.info("JSON parsed successfully")

    if isinstance(parsed, dict):
        theme = parsed.get("theme", {})
        slides = parsed.get("slides", [])
    elif isinstance(parsed, list):
        theme = {}
        slides = parsed
    else:
        logger.error("LLM response is not a JSON object or array")
        sys.exit(1)

    logger.info(f"Parsed {len(slides)} slides, theme: {bool(theme)}")
    return theme, slides


# ─────────────────────────────────────────────────────────────────────
# Rendering — stock reveal.js template, no custom layouts
# ─────────────────────────────────────────────────────────────────────

def prepare_template_slides(raw_slides: list[dict]) -> list[dict]:
    """Convert LLM output to template-ready dicts with title + thanks."""
    result = []

    result.append({
        "title": TITLE_SLIDE["title"],
        "subtitle": TITLE_SLIDE["subtitle"],
        "speaker": TITLE_SLIDE["speaker"],
        "job_title": TITLE_SLIDE.get("job_title"),
        "company": TITLE_SLIDE.get("company"),
        "company_url": TITLE_SLIDE.get("company_url"),
        "event": TITLE_SLIDE.get("event"),
        "bullets": [],
        "speaker_notes": "Welcome everyone!",
        "is_title": True,
        "is_divider": False,
        "is_thanks": False,
        "bg_color": None,
    })

    for i, slide in enumerate(raw_slides):
        result.append({
            "title": slide.get("title", f"Slide {i + 1}"),
            "bullets": slide.get("bullets", []),
            "speaker_notes": slide.get("speaker_notes", ""),
            "is_title": False,
            "is_divider": False,
            "is_thanks": False,
            "bg_color": slide.get("bg_color"),
        })

    result.append({
        "title": THANKS_SLIDE["title"],
        "bullets": THANKS_SLIDE["bullets"],
        "speaker_notes": THANKS_SLIDE["speaker_notes"],
        "is_title": False,
        "is_divider": False,
        "is_thanks": True,
        "bg_color": None,
    })

    return result


def render_html(template_slides: list[dict], topic: str, theme: dict) -> str:
    """Render reveal.js HTML using the stock template."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
    )
    template = env.get_template("reveal_stock.html")

    return template.render(
        title=f"{topic} (Raw LLM)",
        slides=template_slides,
        theme=theme or None,
    )


def make_filename(topic: str, minimal: bool = False) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    suffix = "raw_llm_minimal" if minimal else "raw_llm"
    return f"{ts}_{slug}_{suffix}.html"


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Generate a reveal.js slide deck using raw LLM (no Postgres control plane)"
    )
    parser.add_argument(
        "--topic", type=str, default="Postgres as an AI Control Plane",
        help="Presentation topic (default: 'Postgres as an AI Control Plane')"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path (default: output/<timestamp>_<topic>_raw_llm.html)"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="OpenAI model to use (default: OPENAI_MODEL env or gpt-5)"
    )
    parser.add_argument(
        "--minimal", action="store_true",
        help="Use minimal prompt (topic + audience only, no content plan or quality hints)"
    )
    args = parser.parse_args()

    if args.model:
        os.environ["OPENAI_MODEL"] = args.model

    theme, raw_slides = await generate_slides(args.topic, minimal=args.minimal)

    template_slides = prepare_template_slides(raw_slides)

    html = render_html(template_slides, args.topic, theme)

    output_path = Path(args.output) if args.output else OUTPUT_DIR / make_filename(args.topic, args.minimal)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    prompt_label = "MINIMAL (topic + audience only)" if args.minimal else "GUIDED (per-slide content plan)"
    print(f"\n{'='*60}")
    print(f"  Raw LLM Deck Generated")
    print(f"{'='*60}")
    print(f"  Topic:    {args.topic}")
    print(f"  Prompt:   {prompt_label}")
    print(f"  Slides:   {len(template_slides)} total ({len(raw_slides)} content + title/thanks)")
    print(f"  Template: Stock reveal.js (CDN)")
    print(f"  Output:   {output_path}")
    print(f"  Method:   Single LLM call, NO retrieval, NO gates, NO grounding")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
