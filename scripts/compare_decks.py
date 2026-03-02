"""
Deck Comparison Report — compare raw LLM vs control plane HTML decks.

Three-layer evaluation:
  1. Structural metrics (deterministic HTML parsing)
  2. Automated text metrics (TF-IDF coverage, semantic similarity, vocabulary)
  3. Pairwise LLM comparison (winner per axis, no numeric scales)

Usage:
  python scripts/compare_decks.py
  python scripts/compare_decks.py --analyze
  python scripts/compare_decks.py --analyze --no-store
  python scripts/compare_decks.py --raw X.html --control Y.html --analyze
"""

import argparse
import asyncio
import html as html_mod
import json
import os
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

SLIDE_TYPE_CLASSES = {
    "statement": "statement-text",
    "split": "split-layout",
    "flow": "flow-pipeline",
    "code": "code-block",
    "diagram": "diagram-callout",
}

POSTGRES_TERMS = [
    "pgvector", "pg_trgm", "tsvector", "tsquery", "<=>",
    "SECURITY INVOKER", "REVOKE PUBLIC", "search_path",
    "gate_log", "generation_run", "fn_hybrid_search",
    "cosine", "RRF", "JSONB", "PL/pgSQL",
    "row-level security", "RLS", "ACID",
    "logical replication", "FDW", "PostGIS",
    "pg_stat_statements", "pg_stat_activity",
]


# ─────────────────────────────────────────────────────────────────────
# File discovery
# ─────────────────────────────────────────────────────────────────────

def find_latest(pattern: str) -> Path | None:
    matches = sorted(OUTPUT_DIR.glob(pattern), reverse=True)
    for m in matches:
        if re.match(r"^\d{8}_\d{6}_", m.name):
            return m
    return None


def find_latest_pair() -> tuple[Path | None, Path | None]:
    raw = find_latest("*_raw_llm.html")
    candidates = sorted(OUTPUT_DIR.glob("*.html"), reverse=True)
    ctrl = None
    for c in candidates:
        if not re.match(r"^\d{8}_\d{6}_", c.name):
            continue
        if "_raw_llm" in c.name:
            continue
        ctrl = c
        break
    return raw, ctrl


# ─────────────────────────────────────────────────────────────────────
# Layer 1: Structural metrics
# ─────────────────────────────────────────────────────────────────────

def count_sections(html: str) -> int:
    return len(re.findall(r"<section[\s>]", html))


def detect_slide_types(html: str) -> set[str]:
    found = set()
    for type_name, css_class in SLIDE_TYPE_CLASSES.items():
        if css_class in html:
            found.add(type_name)
    if re.search(r"<ul[\s>]", html):
        found.add("bullets")
    return found


def count_images(html: str) -> int:
    return len(re.findall(r'class="slide-image"', html))


def count_inline_svgs(html: str) -> int:
    return len(re.findall(r"<svg[\s>]", html, re.IGNORECASE))


def count_notes(html: str) -> int:
    return len(re.findall(r'<aside class="notes">', html))


def count_code_blocks(html: str) -> int:
    return len(re.findall(r'<pre[^>]*class="code-block"', html))


def extract_code_languages(html: str) -> list[str]:
    return re.findall(r'data-language="([^"]+)"', html)


def analyze_structure(html: str, filepath: Path) -> dict:
    langs = extract_code_languages(html)
    return {
        "file": filepath.name,
        "total_slides": count_sections(html),
        "slide_types": detect_slide_types(html),
        "images": count_images(html),
        "inline_svgs": count_inline_svgs(html),
        "notes": count_notes(html),
        "code_blocks": count_code_blocks(html),
        "code_languages": langs,
        "size_kb": filepath.stat().st_size / 1024,
    }


def fmt_types(types: set[str]) -> str:
    if len(types) <= 1:
        return f"{len(types)} (bullets only)"
    return f"{len(types)} distinct"


def fmt_code(stats: dict) -> str:
    n = stats["code_blocks"]
    if n == 0:
        return "0"
    langs = ", ".join(sorted(set(stats["code_languages"]))) or "unknown"
    return f"{n} ({langs})"


def print_structural(ctrl: dict, raw: dict):
    SEP = "─" * 68

    def row(label, v1, v2, highlight=False):
        marker = "  <<" if highlight else ""
        print(f"  {label:<24} {v1:<22} {v2:<18}{marker}")

    print()
    print(f"  {SEP}")
    print("  LAYER 1: STRUCTURAL METRICS".center(68))
    print(f"  {SEP}")
    print()
    row("", "Control Plane", "Raw LLM")
    print(f"  {'─' * 24} {'─' * 22} {'─' * 18}")

    row("Total slides",
        str(ctrl["total_slides"]), str(raw["total_slides"]))
    row("Slide types",
        fmt_types(ctrl["slide_types"]), fmt_types(raw["slide_types"]),
        highlight=len(ctrl["slide_types"]) != len(raw["slide_types"]))
    row("Code blocks",
        fmt_code(ctrl), fmt_code(raw),
        highlight=ctrl["code_blocks"] != raw["code_blocks"])
    row("Curated images",
        str(ctrl["images"]), str(raw["images"]),
        highlight=ctrl["images"] != raw["images"])
    row("Inline SVG attempts",
        str(ctrl["inline_svgs"]), str(raw["inline_svgs"]),
        highlight=raw["inline_svgs"] > 0)
    row("Slides with notes",
        f"{ctrl['notes']}/{ctrl['total_slides']}",
        f"{raw['notes']}/{raw['total_slides']}")
    row("File size",
        f"{ctrl['size_kb']:.0f} KB", f"{raw['size_kb']:.0f} KB")
    row("Grounding",
        "Postgres RAG", "LLM training data", highlight=True)
    row("Quality gates",
        "G1-G5 validated", "None", highlight=True)

    print(f"  {SEP}")
    print()


# ─────────────────────────────────────────────────────────────────────
# Text extraction (shared by layers 2 and 3)
# ─────────────────────────────────────────────────────────────────────

def _decode(text: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _is_transition_slide(section_html: str) -> bool:
    """Detect thin transition/divider slides that carry no real content."""
    text = re.sub(r"<[^>]+>", " ", section_html)
    text = " ".join(text.split()).strip()
    return len(text) < 80


def extract_slides(html_src: str) -> list[str]:
    """Return a list of readable text strings, one per slide.

    Transition/divider slides (< 80 chars of text) are stripped so they
    don't inflate repetition or slide-count metrics.
    """
    sections = re.split(r"<section[^>]*>", html_src)[1:]
    stripped_count = 0
    slides = []
    for i, sec in enumerate(sections):
        sec = sec.split("</section>")[0]
        if _is_transition_slide(sec):
            stripped_count += 1
            continue
        sec = re.sub(r"<svg[\s>].*?</svg>", "[inline SVG diagram]", sec, flags=re.DOTALL | re.IGNORECASE)
        sec = re.sub(r'<div class="slide-image">\s*<img[^>]*>\s*</div>',
                      "[curated image]", sec, flags=re.DOTALL)
        title_m = re.search(r"<h[12][^>]*>(.*?)</h[12]>", sec, re.DOTALL)
        title = _decode(title_m.group(1)) if title_m else ""

        bullets_raw = re.findall(r"<li>(.*?)</li>", sec, re.DOTALL)
        bullets = []
        for b in bullets_raw:
            decoded = _decode(b)[:200]
            if not decoded or decoded.startswith("<svg") or decoded == "[inline SVG diagram]":
                continue
            if re.search(r"```\w*", decoded):
                decoded = re.sub(r"```\w*", "", decoded).strip()
                decoded = f"[unrendered code in bullet — not displayed as code block in presentation] {decoded}"
            bullets.append(decoded)

        code_blocks = re.findall(
            r'<pre[^>]*class="code-block"[^>]*>(.*?)</pre>', sec, re.DOTALL
        )
        if not code_blocks:
            code_blocks = re.findall(r"<pre[^>]*>(.*?)</pre>", sec, re.DOTALL)
        code_blocks = [_decode(cb)[:400] for cb in code_blocks]

        lang_m = re.search(r'data-language="([^"]+)"', sec)
        lang = lang_m.group(1) if lang_m else None

        n_curated = sec.count("[curated image]")
        n_svg = sec.count("[inline SVG diagram]")

        notes_m = re.search(r'<aside class="notes">(.*?)</aside>', sec, re.DOTALL)
        notes = _decode(notes_m.group(1))[:300] if notes_m else ""

        if title:
            parts = [f"Slide {i+1}: {title}"]
            if bullets:
                parts.append("  Bullet text:")
                parts.append("  " + "\n  ".join(f"- {b}" for b in bullets))
            if code_blocks:
                parts.append(f"  Rendered code blocks ({len(code_blocks)}):")
                for cb in code_blocks:
                    label = f"[Code block ({lang})]" if lang else "[Code block]"
                    parts.append(f"  {label}:\n    {cb[:300]}")
            if n_curated:
                parts.append(f"  [Contains {n_curated} curated image(s)]")
            if n_svg:
                parts.append(f"  [Contains {n_svg} inline SVG diagram(s)]")
            if notes:
                parts.append(f"  [Notes]: {notes}")
            slides.append("\n".join(parts))

    if stripped_count:
        print(f"  (Stripped {stripped_count} transition/divider slide(s) from text extraction)")
    return slides


def slides_to_text(slides: list[str]) -> str:
    return "\n\n".join(slides)


# ─────────────────────────────────────────────────────────────────────
# Layer 2: Automated text metrics
# ─────────────────────────────────────────────────────────────────────

def compute_auto_metrics(ctrl_slides: list[str], raw_slides: list[str]) -> dict:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine
    import numpy as np

    ctrl_text = slides_to_text(ctrl_slides)
    raw_text = slides_to_text(raw_slides)

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
    tfidf = vectorizer.fit_transform([ctrl_text, raw_text])
    coverage = sklearn_cosine(tfidf[0:1], tfidf[1:2])[0][0]

    try:
        import logging
        logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        ctrl_emb = model.encode(ctrl_slides, convert_to_numpy=True)
        raw_emb = model.encode(raw_slides, convert_to_numpy=True)
        sim_matrix = sklearn_cosine(ctrl_emb, raw_emb)
        n = min(len(ctrl_slides), len(raw_slides))
        per_slide = [sim_matrix[i][i] for i in range(n)]
        best_match = [sim_matrix[i].max() for i in range(len(ctrl_slides))]
        semantic_avg = float(np.mean(best_match))
        semantic_available = True
    except Exception:
        semantic_avg = None
        semantic_available = False

    ctrl_lower = ctrl_text.lower()
    raw_lower = raw_text.lower()
    ctrl_terms = [t for t in POSTGRES_TERMS if t.lower() in ctrl_lower]
    raw_terms = [t for t in POSTGRES_TERMS if t.lower() in raw_lower]
    shared_terms = [t for t in ctrl_terms if t.lower() in raw_lower]

    return {
        "tfidf_coverage": float(coverage),
        "semantic_similarity": semantic_avg,
        "semantic_available": semantic_available,
        "ctrl_vocab": ctrl_terms,
        "raw_vocab": raw_terms,
        "shared_vocab": shared_terms,
        "baseline_only": [t for t in ctrl_terms if t not in shared_terms],
        "raw_only": [t for t in raw_terms if t.lower() not in ctrl_lower],
    }


def print_auto_metrics(m: dict):
    W = 68
    SEP = "─" * W

    print(f"  {SEP}")
    print("  LAYER 2: AUTOMATED TEXT METRICS (deterministic)".center(W))
    print(f"  {SEP}")
    print()
    print(f"  {'Metric':<24} {'Score':>8}  Method")
    print(f"  {'─' * 24} {'─' * 8}  {'─' * 32}")

    pct = m["tfidf_coverage"] * 100
    print(f"  {'Content coverage':<24} {pct:>7.0f}%  TF-IDF cosine of full deck text")

    if m["semantic_available"]:
        sim = m["semantic_similarity"]
        print(f"  {'Semantic similarity':<24} {sim:>8.2f}  avg best-match cosine (sentence-transformers)")
    else:
        print(f"  {'Semantic similarity':<24} {'N/A':>8}  sentence-transformers not available")

    ctrl_n = len(m["ctrl_vocab"])
    shared_n = len(m["shared_vocab"])
    print(f"  {'Technical vocabulary':<24} {shared_n:>3} / {ctrl_n:<3}  raw uses {shared_n} of {ctrl_n} baseline terms")

    if m["baseline_only"]:
        terms = ", ".join(m["baseline_only"][:8])
        print(f"  {'  Baseline only':<24}         {terms}")
    if m["raw_only"]:
        terms = ", ".join(m["raw_only"][:8])
        print(f"  {'  Raw LLM only':<24}         {terms}")

    print()
    print(f"  {SEP}")
    print()


# ─────────────────────────────────────────────────────────────────────
# Layer 3: Pairwise LLM comparison
# ─────────────────────────────────────────────────────────────────────

PAIRWISE_PROMPT = """\
You are a strict technical reviewer comparing two slide decks.

TALK CONTEXT: This is a 25-minute conference talk at SCaLE 23x (a \
Linux/open-source conference) for an audience of developers and DBAs. \
The topic is "Postgres as an AI Control Plane" — arguing that Postgres \
features (extensions, security primitives, SQL) can replace scattered \
AI infrastructure services. The audience expects concrete Postgres \
examples, not marketing-level abstractions.

Deck A was generated by a multi-step pipeline: one slide at a time, \
with quality gates that reject weak slides, structured slide types \
(code, split, diagram, etc.), curated images, and RAG retrieval from \
Postgres documentation fragments.
Note: This topic (Postgres features, pgvector, MCP) is public knowledge \
already in the LLM's training data. RAG here acts as a specificity \
constraint (steering toward particular examples), not as a source of \
novel information. Judge both decks on what they actually contain, \
not on how they were produced.
Deck B was generated by a single LLM call with no retrieval, no \
validation, no multi-step generation, and a stock reveal.js template.

For each axis below, determine which deck is better. The winner can be \
"A", "B", or "tie". Every judgment MUST cite specific evidence from \
the slide text.

AXES:
- specificity: Which deck names real Postgres features at a more \
concrete level? (operators, function names, table schemas vs. feature categories)
- accuracy: Which deck's technical claims are more verifiably correct? \
Look for: hallucinated function/operator names, wrong syntax, \
incorrect version claims, or features attributed to the wrong extension. \
Naming a plausible-sounding table or function that doesn't actually exist \
is a hallucination, not depth. If a deck mentions specific table names or \
schemas, ask yourself: are these real names from a working system, or \
invented examples? Invented schemas presented as real are inaccurate.
- repetition: Which deck has less content overlap between slides? \
For EACH deck, find pairs of slides that share the same bullet points, \
examples, feature names, or explanations. Repeating a thesis statement \
("Postgres is the control plane") is normal framing and does NOT count. \
What counts: same bullet appearing on 2+ slides, same feature explained \
twice, same example/code repeated, or same list of capabilities restated. \
slightly = 1-2 overlapping pairs; moderately = 3-4; significantly = 5+. \
In your reason, cite the specific overlapping content.
- depth: Which deck provides more implementation detail? \
(schemas, queries, function signatures vs. abstractions) \
Describing a schema in bullet text is less deep than showing the actual \
SQL that creates or queries it. Invented-sounding table names in prose \
are descriptions, not implementations.
- code_examples: Which deck includes more real, runnable code blocks? \
IMPORTANT: Only count items marked "Rendered code blocks" or "[Code block]" \
in the extracted text. Bullet text that describes schemas in prose \
(e.g. "documents(id, source, title)") is NOT a code block — it's a \
description. A real code block is rendered <pre> content with actual \
runnable SQL, TypeScript, or similar.
- formatting: Which deck has more visual variety and structural diversity? \
(curated images, inline diagrams, code blocks, multiple slide layouts)

MARGIN SCALE (how big is the gap?):
- "tie" = essentially equivalent
- "slightly" = minor edge, reasonable people could disagree
- "moderately" = clear difference with concrete evidence
- "significantly" = large gap, one deck is much stronger

Return ONLY valid JSON, no markdown fences. Keep each reason under 30 words.
{"comparisons": {
  "specificity": {"winner": "A|B|tie", "margin": "MARGIN", "reason": "≤30 words"},
  "accuracy": {"winner": "A|B|tie", "margin": "MARGIN", "reason": "≤30 words"},
  "repetition": {"winner": "A|B|tie", "margin": "MARGIN", "reason": "≤30 words"},
  "depth": {"winner": "A|B|tie", "margin": "MARGIN", "reason": "≤30 words"},
  "code_examples": {"winner": "A|B|tie", "margin": "MARGIN", "reason": "≤30 words"},
  "formatting": {"winner": "A|B|tie", "margin": "MARGIN", "reason": "≤30 words"}
},
"key_differences": ["one sentence each", "...", "..."]}

DECK A (Control Plane):
%CTRL%

DECK B (Raw LLM):
%RAW%"""

COMPARISON_AXES = [
    ("Specificity", "specificity"),
    ("Accuracy", "accuracy"),
    ("Repetition", "repetition"),
    ("Technical depth", "depth"),
    ("Code examples", "code_examples"),
    ("Formatting", "formatting"),
]

WINNER_MAP = {"a": "Baseline", "b": "Raw LLM", "tie": "Tie"}


def print_pairwise(result: dict):
    comparisons = result.get("comparisons", {})
    diffs = result.get("key_differences", [])

    W = 72
    SEP = "─" * W

    print(f"  {SEP}")
    print("  LAYER 3: PAIRWISE COMPARISON (LLM-evaluated)".center(W))
    print(f"  {SEP}")
    print()
    print(f"  {'':20} {'Winner':<12} {'Margin':<16} Reason")
    print(f"  {'─' * 20} {'─' * 12} {'─' * 16} {'─' * 20}")

    baseline_wins = 0
    raw_wins = 0
    ties = 0

    for label, key in COMPARISON_AXES:
        c = comparisons.get(key, {})
        winner_raw = c.get("winner", "tie").lower().strip()
        margin = c.get("margin", "tie").lower().strip()
        reason = c.get("reason", "")

        if winner_raw == "tie":
            margin = "tie"
        elif margin == "tie" and winner_raw in ("a", "b"):
            margin = "slightly"

        winner = WINNER_MAP.get(winner_raw, winner_raw.title())
        if winner_raw == "a":
            baseline_wins += 1
        elif winner_raw == "b":
            raw_wins += 1
        else:
            ties += 1

        margin_display = margin if margin != "tie" else ""
        short_reason = (reason[:40] + "...") if len(reason) > 43 else reason
        print(f"  {label:<20} {winner:<12} {margin_display:<16} {short_reason}")

    print(f"  {'─' * 20} {'─' * 12} {'─' * 16}")

    parts = []
    if baseline_wins:
        parts.append(f"Baseline wins {baseline_wins}")
    if raw_wins:
        parts.append(f"Raw LLM wins {raw_wins}")
    if ties:
        parts.append(f"{ties} tie{'s' if ties > 1 else ''}")
    print(f"  Result: {', '.join(parts)}  (of {len(COMPARISON_AXES)} axes)")

    if diffs:
        print()
        print("  Key differences:")
        for d in diffs:
            wrapped = textwrap.fill(d, width=68, initial_indent="  - ", subsequent_indent="    ")
            print(wrapped)

    print()
    print(f"  {SEP}")
    print()


async def run_llm_comparison(ctrl_text: str, raw_text: str) -> dict | None:
    """Run a single pairwise LLM comparison. Returns parsed result dict or None on failure."""
    import httpx
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("  ERROR: OPENAI_API_KEY not set — skipping LLM comparison")
        return None

    base_url = os.getenv("OPENAI_API_BASE")
    ssl_verify = os.getenv("SSL_VERIFY", "true").lower() != "false"
    http_client = None if ssl_verify else httpx.AsyncClient(verify=False)

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    if http_client:
        client_kwargs["http_client"] = http_client
    client = AsyncOpenAI(**client_kwargs)

    prompt = PAIRWISE_PROMPT.replace("%CTRL%", ctrl_text).replace("%RAW%", raw_text)

    model = os.getenv("OPENAI_MODEL", "gpt-5")
    user = os.getenv("OPENAI_USER")
    print(f"  Running pairwise LLM comparison with {model}...")

    req_kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4000,
    }
    if user:
        req_kwargs["user"] = user

    response = await client.chat.completions.create(**req_kwargs)

    text = (response.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        print(f"  Failed to parse LLM response:\n  {text[:500]}")
        return None

    return result


# ─────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────

def _count_winners(result: dict) -> tuple[int, int, int]:
    baseline_wins = raw_wins = ties = 0
    for _, key in COMPARISON_AXES:
        c = result.get("comparisons", {}).get(key, {})
        w = c.get("winner", "tie").lower().strip()
        if w == "a":
            baseline_wins += 1
        elif w == "b":
            raw_wins += 1
        else:
            ties += 1
    return baseline_wins, raw_wins, ties


async def store_comparison(
    result: dict,
    metrics: dict,
    raw_path: Path,
    ctrl_path: Path,
    prompt_type: str,
) -> None:
    import asyncpg
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("  WARNING: DATABASE_URL not set — skipping storage")
        return

    baseline_wins, raw_wins, ties = _count_winners(result)
    model = os.getenv("OPENAI_MODEL", "gpt-5")

    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(
            """
            INSERT INTO comparison_run (
                raw_deck_file, ctrl_deck_file, prompt_type, model, temperature,
                tfidf_coverage, semantic_sim, vocab_shared, vocab_baseline,
                comparisons, key_differences,
                baseline_wins, raw_wins, ties
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            """,
            raw_path.name,
            ctrl_path.name,
            prompt_type,
            model,
            0.3,
            metrics.get("tfidf_coverage"),
            metrics.get("semantic_similarity"),
            len(metrics.get("shared_vocab", [])),
            len(metrics.get("ctrl_vocab", [])),
            json.dumps(result.get("comparisons", {})),
            json.dumps(result.get("key_differences", [])),
            baseline_wins,
            raw_wins,
            ties,
        )
        print(f"  Stored comparison run to Postgres")
    finally:
        await conn.close()


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def _detect_prompt_type(raw_path: Path) -> str:
    return "minimal" if "minimal" in raw_path.name else "guided"


def main():
    parser = argparse.ArgumentParser(description="Compare raw LLM vs control plane decks")
    parser.add_argument("--raw", type=str, default=None, help="Path to raw LLM HTML")
    parser.add_argument("--control", type=str, default=None, help="Path to control plane HTML")
    parser.add_argument("--analyze", action="store_true", help="Run all three evaluation layers (auto-stores to Postgres)")
    parser.add_argument("--no-store", action="store_true", help="Skip storing results to Postgres")
    parser.add_argument("--runs", type=int, default=1, help="Number of LLM comparison runs (default: 1)")
    args = parser.parse_args()

    if args.runs > 1 and not args.analyze:
        print("ERROR: --runs requires --analyze")
        return

    if args.raw and args.control:
        raw_path = Path(args.raw)
        ctrl_path = Path(args.control)
    else:
        raw_path, ctrl_path = find_latest_pair()

    if not raw_path or not raw_path.exists():
        print("ERROR: No raw LLM deck found in output/")
        print("  Run: python scripts/generate_raw_llm_deck.py")
        return

    if not ctrl_path or not ctrl_path.exists():
        print("ERROR: No control plane deck found in output/")
        print("  Run: python -m src.server --topic 'Postgres as an AI Control Plane'")
        return

    print(f"  Raw LLM:       {raw_path.name}")
    print(f"  Control Plane: {ctrl_path.name}")

    raw_html = raw_path.read_text(encoding="utf-8")
    ctrl_html = ctrl_path.read_text(encoding="utf-8")

    ctrl_stats = analyze_structure(ctrl_html, ctrl_path)
    raw_stats = analyze_structure(raw_html, raw_path)
    print_structural(ctrl_stats, raw_stats)

    if args.analyze:
        ctrl_slides = extract_slides(ctrl_html)
        raw_slides = extract_slides(raw_html)

        print("  Computing automated metrics...")
        metrics = compute_auto_metrics(ctrl_slides, raw_slides)
        print_auto_metrics(metrics)

        ctrl_text = slides_to_text(ctrl_slides)
        raw_text = slides_to_text(raw_slides)
        prompt_type = _detect_prompt_type(raw_path)

        async def run_comparisons():
            for i in range(args.runs):
                if args.runs > 1:
                    print(f"\n  ─── Run {i + 1} of {args.runs} ───")
                result = await run_llm_comparison(ctrl_text, raw_text)
                if result:
                    print_pairwise(result)
                    if not args.no_store:
                        await store_comparison(result, metrics, raw_path, ctrl_path, prompt_type)

        asyncio.run(run_comparisons())

        if args.runs > 1:
            print(f"  Completed {args.runs} comparison runs.")
            if not args.no_store:
                print(f"  View aggregated results: python scripts/comparison_summary.py")


if __name__ == "__main__":
    main()
