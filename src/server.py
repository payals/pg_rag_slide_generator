"""
Live Slide Deck Server with Progressive SSE Streaming.

Serves a reveal.js deck that updates in real-time as slides are generated.
Two event channels feed the browser:
  1. Postgres LISTEN/NOTIFY -- fires when slides are committed and gate_log
     rows are written (batched at transaction commit)
  2. In-process progress queue -- the orchestrator pushes phase/cost/intent
     updates directly to the server (real-time, no DB round-trip)

Usage:
    python -m src.server --topic "Postgres as AI Application Server"
    python -m src.server --deck-id <uuid> --port 8000
"""

import argparse
import asyncio
import json
import logging
import os
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import UUID

import asyncpg
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from src.db import init_pool, close_pool, get_connection
from src.mcp_client import tool_call, init_mcp_client, close_mcp_client
from src.orchestrator import run_generation_headless, cleanup_stale_generating
from src.renderer import (
    OUTPUT_DIR,
    get_jinja_env,
    get_target_slides,
    get_title_slide,
    get_thanks_slide,
    get_themes,
    render_single_slide_html,
    render_deck,
    export_html,
    make_deck_filename,
    init_renderer,
)

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# ============================================================================
# Module-level state
# ============================================================================
progress_queue: Optional[asyncio.Queue] = None
sse_clients: list = []
generation_task: Optional[asyncio.Task] = None
listen_conn: Optional[asyncpg.Connection] = None
sent_dividers: set = set()

# CLI arguments stored here by __main__
_config = {
    "deck_id": None,
    "topic": None,
    "target_slides": None,
    "theme": "dark",
    "port": 8000,
    "no_browser": False,
    "save_deck": True,
}


# ============================================================================
# Postgres LISTEN handler
# ============================================================================

async def setup_listen(deck_id: str):
    """Set up a dedicated LISTEN connection (not from pool)."""
    global listen_conn
    listen_conn = await asyncpg.connect(DATABASE_URL)
    await listen_conn.add_listener("slide_committed", _on_slide_notify)
    await listen_conn.add_listener("gate_update", _on_gate_notify)
    logger.info("LISTEN connections established for slide_committed and gate_update")


def _on_slide_notify(conn, pid, channel, payload):
    """Callback from Postgres NOTIFY on slide_committed channel."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning(f"Invalid NOTIFY payload: {payload}")
        return
    # Filter by deck_id (Issue 6)
    if data.get("deck_id") != _config["deck_id"]:
        return
    asyncio.create_task(_handle_slide_committed(data))


def _on_gate_notify(conn, pid, channel, payload):
    """Callback from Postgres NOTIFY on gate_update channel."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning(f"Invalid NOTIFY payload: {payload}")
        return
    if data.get("deck_id") != _config["deck_id"]:
        return
    asyncio.create_task(_handle_gate_update(data))


async def _handle_slide_committed(data: dict):
    """Load full slide from DB, render HTML fragment, fan out to SSE clients."""
    global sent_dividers

    try:
        slide = await _load_slide(data["deck_id"], data["slide_no"])
        if not slide:
            logger.warning(f"Slide not found: deck={data['deck_id']}, no={data['slide_no']}")
            return

        html, sent_dividers = render_single_slide_html(slide, sent_dividers)
        slides_ready = await _count_slides(data["deck_id"])

        event = {
            "type": "slide_added",
            "data": {
                "html": html,
                "intent": data.get("intent", ""),
                "slide_no": data["slide_no"],
                "slides_ready": slides_ready,
                "total": _config["target_slides"],
            },
        }
        for client in sse_clients:
            await client.put(event)
    except Exception as e:
        logger.error(f"Error handling slide_committed: {e}", exc_info=True)


async def _handle_gate_update(data: dict):
    """Fan out gate_update event to SSE clients."""
    event = {
        "type": "gate_update",
        "data": data,
    }
    for client in sse_clients:
        await client.put(event)


# ============================================================================
# DB helpers
# ============================================================================

async def _load_slide(deck_id: str, slide_no: int) -> Optional[dict]:
    """Load a single slide row from the database."""
    async with get_connection() as conn:
        row = await conn.fetchrow("""
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
                ia.storage_path as image_path,
                ia.alt_text as image_alt
            FROM slide s
            LEFT JOIN image_asset ia ON s.image_id = ia.image_id
            WHERE s.deck_id = $1 AND s.slide_no = $2
        """, UUID(deck_id), slide_no)
        return dict(row) if row else None


async def _count_slides(deck_id: str) -> int:
    """Count committed slides for a deck."""
    async with get_connection() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM slide WHERE deck_id = $1",
            UUID(deck_id),
        )


async def _load_initial_slides(deck_id: str) -> list:
    """Load all already-committed slides for catch-up / resume."""
    global sent_dividers
    async with get_connection() as conn:
        rows = await conn.fetch("""
            SELECT
                s.slide_no,
                s.intent::text as intent,
                s.title,
                s.bullets,
                s.speaker_notes,
                s.citations,
                s.slide_type::text as slide_type,
                s.content_data,
                ia.storage_path as image_path,
                ia.alt_text as image_alt
            FROM slide s
            LEFT JOIN image_asset ia ON s.image_id = ia.image_id
            WHERE s.deck_id = $1
            ORDER BY s.slide_no
        """, UUID(deck_id))

    result = []
    for row in rows:
        slide = dict(row)
        html, sent_dividers = render_single_slide_html(slide, sent_dividers)
        result.append({"html": html, "intent": slide["intent"]})
    return result


async def _get_catchup_events(deck_id: str) -> list:
    """Build catch-up SSE events for all already-committed slides."""
    async with get_connection() as conn:
        rows = await conn.fetch("""
            SELECT
                s.slide_no,
                s.intent::text as intent,
                s.title,
                s.bullets,
                s.speaker_notes,
                s.citations,
                s.slide_type::text as slide_type,
                s.content_data,
                ia.storage_path as image_path,
                ia.alt_text as image_alt
            FROM slide s
            LEFT JOIN image_asset ia ON s.image_id = ia.image_id
            WHERE s.deck_id = $1
            ORDER BY s.slide_no
        """, UUID(deck_id))

    catchup_dividers = set()
    events = []
    for row in rows:
        slide = dict(row)
        html, catchup_dividers = render_single_slide_html(slide, catchup_dividers)
        events.append({
            "type": "slide_added",
            "data": {
                "html": html,
                "intent": slide["intent"],
                "slide_no": slide["slide_no"],
                "slides_ready": len(events) + 1,
                "total": _config["target_slides"],
            },
        })
    return events


# ============================================================================
# Progress queue consumer
# ============================================================================

async def consume_progress():
    """Read from in-process progress queue, fan out to SSE clients."""
    while True:
        msg = await progress_queue.get()
        event_type = msg.pop("type", "progress")
        # SSE 'error' is reserved -- rename to 'error_event'
        if event_type == "error":
            event_type = "error_event"
        # Inject authoritative slide count from DB to fix race with NOTIFY
        if event_type == "complete" and _config["deck_id"]:
            msg["slides_ready"] = await _count_slides(_config["deck_id"])
            msg["total"] = _config["target_slides"]
        event = {"type": event_type, "data": msg}
        for client in sse_clients:
            await client.put(event)
        if event_type == "complete":
            # Save static HTML to output/ for offline use
            await _save_deck_to_output()
            break
        if event_type == "error_event":
            break


async def _save_deck_to_output():
    """Render the completed deck and save to output/ directory."""
    deck_id = _config["deck_id"]
    if not deck_id or not _config.get("save_deck", True):
        return
    try:
        theme = _config.get("theme", "dark")
        html = await render_deck(UUID(deck_id), theme=theme)
        topic = _config.get("topic") or deck_id[:8]
        output_path = OUTPUT_DIR / make_deck_filename(topic)
        export_html(html, output_path)
        logger.info(f"Deck saved to {output_path}")

        # Notify SSE clients about the saved file
        save_event = {
            "type": "deck_saved",
            "data": {"path": str(output_path)},
        }
        for client in sse_clients:
            await client.put(save_event)
    except Exception as e:
        logger.error(f"Failed to save deck to output: {e}", exc_info=True)


# ============================================================================
# FastAPI lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup / shutdown lifecycle."""
    global generation_task, progress_queue

    # --- Startup ---
    await init_pool()
    from src import config
    await config.init_config()
    await init_mcp_client()
    await init_renderer()
    _config["target_slides"] = get_target_slides()
    await cleanup_stale_generating()
    progress_queue = asyncio.Queue()

    # Create or load deck
    deck_id = _config["deck_id"]
    topic = _config["topic"]
    target_slides = _config["target_slides"]

    if deck_id is None and topic:
        deck_id = await tool_call("mcp_create_deck", topic=topic, target_slides=target_slides)
        _config["deck_id"] = deck_id
        logger.info(f"Created new deck: {deck_id}")
    elif deck_id:
        logger.info(f"Using existing deck: {deck_id}")
    else:
        raise ValueError("Either --topic or --deck-id must be provided")

    # Set up LISTEN
    await setup_listen(deck_id)

    # Launch orchestrator in background
    generation_task = asyncio.create_task(
        run_generation_headless(
            deck_id=deck_id,
            topic=topic,
            target_slides=target_slides,
            progress_queue=progress_queue,
        )
    )

    # Launch progress consumer
    asyncio.create_task(consume_progress())

    # Delay browser open until server is listening (Issue 13)
    if not _config["no_browser"]:
        port = _config["port"]
        asyncio.get_event_loop().call_later(
            1.5, lambda: webbrowser.open(f"http://localhost:{port}")
        )

    yield  # Server runs here

    # --- Shutdown (Issue 15) ---
    if generation_task and not generation_task.done():
        generation_task.cancel()
        try:
            await generation_task
        except asyncio.CancelledError:
            pass
    if listen_conn:
        await listen_conn.close()
    await close_mcp_client()
    await close_pool()


# ============================================================================
# FastAPI app
# ============================================================================

app = FastAPI(lifespan=lifespan, title="Live Slide Deck Server")

# Mount static images
images_dir = Path("content/images")
if images_dir.exists():
    app.mount("/images", StaticFiles(directory=str(images_dir)), name="images")


# ============================================================================
# Endpoints
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the live deck page."""
    deck_id = _config["deck_id"]
    target_slides = _config["target_slides"]
    theme = _config["theme"]

    env = get_jinja_env()
    template = env.get_template("reveal_live.html")

    # Load any already-committed slides for resume support
    initial_slides = await _load_initial_slides(deck_id)

    themes = get_themes()
    theme_config = themes.get(theme, themes["dark"])

    html = template.render(
        title=get_title_slide()["title"],
        title_slide=get_title_slide(),
        thanks_slide=get_thanks_slide(),
        deck_id=deck_id,
        target_slides=target_slides,
        initial_slides=initial_slides,
        theme_overrides=theme_config["overrides"],
        logo_path="/images/netapp_logo.png",
    )
    return HTMLResponse(html)


@app.get("/api/stream/{did}")
async def stream(did: str):
    """SSE endpoint for progressive deck updates."""
    client_queue: asyncio.Queue = asyncio.Queue()
    sse_clients.append(client_queue)

    async def event_generator():
        try:
            # On connect, send catch-up burst of all committed slides
            for slide_event in await _get_catchup_events(did):
                yield {
                    "event": slide_event["type"],
                    "data": json.dumps(slide_event["data"]),
                    "retry": 3000,
                }

            # Then stream new events
            while True:
                event = await client_queue.get()
                yield {
                    "event": event["type"],
                    "data": json.dumps(event["data"]),
                    "retry": 3000,
                }
                # Stop streaming after completion
                if event["type"] in ("complete", "error_event"):
                    break
        finally:
            if client_queue in sse_clients:
                sse_clients.remove(client_queue)

    return EventSourceResponse(event_generator())


_deck_stats_cache: Optional[dict] = None


@app.get("/api/stats/{did}")
async def slide_stats(did: str, slide_no: Optional[int] = Query(None)):
    """Return telemetry stats for the post-generation panel.

    If slide_no is provided, returns per-slide stats alongside deck-wide stats.
    Deck-wide stats are cached in memory since they don't change post-generation.
    """
    global _deck_stats_cache
    try:
        deck_uuid = UUID(did)
    except ValueError:
        return JSONResponse({"error": "invalid deck_id"}, status_code=400)

    # --- Deck-wide stats (cached after first fetch) ---
    if _deck_stats_cache is None or _deck_stats_cache.get("deck_id") != did:
        try:
            async with get_connection() as conn:
                health_row = await conn.fetchrow(
                    "SELECT slide_count, total_retries, avg_retries_per_slide, "
                    "total_gate_failures, slides_with_failures, completion_pct "
                    "FROM v_deck_health WHERE deck_id = $1",
                    deck_uuid,
                )
                coverage_row = await conn.fetchrow(
                    "SELECT covered_intents, total_slides, missing "
                    "FROM v_deck_coverage WHERE deck_id = $1",
                    deck_uuid,
                )
                total_gates = await conn.fetchval(
                    "SELECT COUNT(*) FROM gate_log WHERE deck_id = $1",
                    deck_uuid,
                )
                total_passes = await conn.fetchval(
                    "SELECT COUNT(*) FROM gate_log WHERE deck_id = $1 AND decision = 'pass'",
                    deck_uuid,
                )
                top_failure_row = await conn.fetchrow(
                    "SELECT gate_name, occurrence_count FROM v_gate_failures "
                    "WHERE deck_id = $1 AND decision = 'fail' "
                    "ORDER BY occurrence_count DESC LIMIT 1",
                    deck_uuid,
                )
                top_source_row = await conn.fetchrow(
                    "SELECT doc_title, citation_count FROM v_top_sources "
                    "WHERE deck_id = $1 ORDER BY citation_count DESC LIMIT 1",
                    deck_uuid,
                )
                run_row = await conn.fetchrow(
                    "SELECT llm_calls, prompt_tokens, completion_tokens, "
                    "embedding_tokens, estimated_cost_usd, started_at, completed_at "
                    "FROM generation_run WHERE deck_id = $1 "
                    "ORDER BY started_at DESC LIMIT 1",
                    deck_uuid,
                )
                doc_count = await conn.fetchval("SELECT COUNT(*) FROM doc")
                chunk_count = await conn.fetchval("SELECT COUNT(*) FROM chunk")
                avg_citation_count = await conn.fetchval(
                    "SELECT COALESCE(AVG(jsonb_array_length(citations)), 0) "
                    "FROM slide WHERE deck_id = $1 AND citations IS NOT NULL "
                    "AND jsonb_array_length(citations) > 0",
                    deck_uuid,
                )

            h = dict(health_row) if health_row else {}
            c = dict(coverage_row) if coverage_row else {}
            r = dict(run_row) if run_row else {}
            pass_rate = round(total_passes / total_gates * 100, 1) if total_gates else 0
            total_gen_seconds = (
                float((r["completed_at"] - r["started_at"]).total_seconds())
                if r.get("started_at") and r.get("completed_at") else None
            )
            completion_pct = float(h.get("completion_pct", 0) or 0)
            avg_retries = float(h.get("avg_retries_per_slide", 0) or 0)
            retry_efficiency = max(0, 100 - avg_retries * 20)
            health_score = round(pass_rate * 0.5 + completion_pct * 0.3 + retry_efficiency * 0.2)

            _deck_stats_cache = {
                "deck_id": did,
                "total_gate_checks": total_gates,
                "total_passes": total_passes,
                "pass_rate": pass_rate,
                "total_retries": h.get("total_retries", 0),
                "total_gate_failures": h.get("total_gate_failures", 0),
                "slide_count": h.get("slide_count", 0),
                "completion_pct": float(h.get("completion_pct", 0) or 0),
                "covered_intents": c.get("covered_intents", 0),
                "missing_intents": [str(m) for m in c.get("missing", [])] if c.get("missing") else [],
                "top_failure_gate": dict(top_failure_row) if top_failure_row else None,
                "top_source": {
                    "title": top_source_row["doc_title"],
                    "citations": top_source_row["citation_count"],
                } if top_source_row else None,
                "llm_calls": r.get("llm_calls", 0),
                "prompt_tokens": r.get("prompt_tokens", 0),
                "completion_tokens": r.get("completion_tokens", 0),
                "embedding_tokens": r.get("embedding_tokens", 0),
                "estimated_cost_usd": float(r.get("estimated_cost_usd", 0) or 0),
                "doc_count": doc_count,
                "chunk_count": chunk_count,
                "total_gen_seconds": total_gen_seconds,
                "health_score": health_score,
                "deck_averages": {
                    "avg_retry_count": float(h.get("avg_retries_per_slide", 0) or 0),
                    "avg_gate_failures": (
                        h.get("total_gate_failures", 0) / h["slide_count"]
                        if h.get("slide_count") else 0
                    ),
                    "avg_citation_count": float(avg_citation_count or 0),
                },
            }
        except Exception as e:
            logger.error(f"Failed to fetch deck stats for {did}: {e}", exc_info=True)
            return JSONResponse({"error": "failed to fetch deck stats", "detail": str(e)}, status_code=500)

    result = {"deck": _deck_stats_cache}

    # --- Per-slide stats (not cached, but these are fast indexed lookups) ---
    if slide_no is not None:
        try:
            async with get_connection() as conn:
                slide_row = await conn.fetchrow(
                    "SELECT intent::text, slide_type::text, title, retry_count, citations "
                    "FROM slide WHERE deck_id = $1 AND slide_no = $2",
                    deck_uuid, slide_no,
                )
                gate_fail_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM gate_log "
                    "WHERE deck_id = $1 AND slide_no = $2 AND decision = 'fail'",
                    deck_uuid, slide_no,
                )
                gate_pass_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM gate_log "
                    "WHERE deck_id = $1 AND slide_no = $2 AND decision = 'pass'",
                    deck_uuid, slide_no,
                )
                top_fail_reason = await conn.fetchrow(
                    "SELECT gate_name, reason FROM gate_log "
                    "WHERE deck_id = $1 AND slide_no = $2 AND decision = 'fail' "
                    "ORDER BY created_at DESC LIMIT 1",
                    deck_uuid, slide_no,
                )
                gate_scores = await conn.fetch(
                    "SELECT gate_name, ROUND(score::numeric, 2) as score FROM gate_log "
                    "WHERE deck_id = $1 AND slide_no = $2 AND decision = 'pass' AND score IS NOT NULL "
                    "ORDER BY created_at",
                    deck_uuid, slide_no,
                )
                gen_seconds_val = await conn.fetchval(
                    "SELECT EXTRACT(EPOCH FROM MAX(created_at) - MIN(created_at)) "
                    "FROM gate_log WHERE deck_id = $1 AND slide_no = $2",
                    deck_uuid, slide_no,
                )

            if slide_row:
                s = dict(slide_row)
                citations = s.get("citations") or []
                if isinstance(citations, str):
                    try:
                        citations = json.loads(citations)
                    except (json.JSONDecodeError, TypeError):
                        citations = []
                citation_count = len(citations) if isinstance(citations, list) else 0
                top_cited = None
                if citation_count > 0 and isinstance(citations[0], dict):
                    top_cited = citations[0].get("title") or citations[0].get("doc_title")

                result["slide"] = {
                    "slide_no": slide_no,
                    "intent": s.get("intent"),
                    "slide_type": s.get("slide_type"),
                    "title": s.get("title"),
                    "retry_count": s.get("retry_count", 0),
                    "gate_failures": gate_fail_count,
                    "gate_passes": gate_pass_count,
                    "top_fail_reason": dict(top_fail_reason) if top_fail_reason else None,
                    "gate_scores": {str(r["gate_name"]): float(r["score"]) for r in gate_scores},
                    "citation_count": citation_count,
                    "top_cited_source": top_cited,
                    "gen_seconds": float(gen_seconds_val) if gen_seconds_val is not None else None,
                }
        except Exception as e:
            logger.warning(f"Failed to fetch slide stats for slide_no={slide_no}: {e}")

    return result


@app.get("/health")
async def health():
    """Health check endpoint (Issue 16)."""
    return {
        "status": "ok",
        "deck_id": _config["deck_id"],
        "generating": generation_task is not None and not generation_task.done(),
        "slides_ready": await _count_slides(_config["deck_id"]) if _config["deck_id"] else 0,
    }


# ============================================================================
# CLI entry point
# ============================================================================

def main():
    """CLI entry point for live server."""
    parser = argparse.ArgumentParser(
        description="Live Slide Deck Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate new deck live
  python -m src.server --topic "Postgres as AI Application Server"

  # Resume existing deck
  python -m src.server --deck-id <uuid>

  # Custom port and theme
  python -m src.server --topic "My Talk" --port 3000 --theme postgres
        """,
    )
    parser.add_argument("--topic", type=str, help="Topic for new deck")
    parser.add_argument("--deck-id", type=str, help="UUID of existing deck")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    parser.add_argument("--theme", type=str, default="dark", help="Theme (default: dark)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    parser.add_argument("--no-save", action="store_true", help="Don't save deck to output/ on completion")

    args = parser.parse_args()

    if not args.deck_id and not args.topic:
        parser.error("Either --deck-id or --topic must be provided")

    # Store config for lifespan access
    _config["deck_id"] = args.deck_id
    _config["topic"] = args.topic
    _config["theme"] = args.theme
    _config["port"] = args.port
    _config["no_browser"] = args.no_browser
    _config["save_deck"] = not args.no_save

    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
