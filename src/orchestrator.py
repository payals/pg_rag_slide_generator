"""
Slide Generation Orchestrator using LangGraph.

Coordinates between Postgres (control plane) and the LLM (drafting).
Implements the gate validation sequence:
G1 (retrieval) -> G3 (format) -> G2 (citations) -> G2.5 (grounding) -> G4 (novelty) -> G5 (image + commit)

Usage:
    # Run generation for a new deck
    python -m src.orchestrator --topic "Postgres as AI Application Server"
    
    # Continue generation for existing deck
    python -m src.orchestrator --deck-id <uuid>
"""

import argparse
import asyncio
import json
import logging
import random
import sys
from typing import Any, Literal, Optional, TypedDict
from uuid import UUID, uuid4

from langgraph.graph import StateGraph, END

from src.db import init_pool, close_pool, get_connection
from src.models import load_intent_type_map, load_slide_type_configs, load_prompt_templates, extract_slide_text, should_select_image, INTENT_TYPE_MAP
from src.llm import (
    LLMResponse,
    draft_slide,
    rewrite_slide_format,
    rewrite_slide_grounding,
    rewrite_slide_novelty,
    generate_alternative_queries,
    InsufficientContextError,
    ParseError,
    LLMError,
    get_intent_metadata,
)
from src.mcp_client import tool_call, init_mcp_client, close_mcp_client
from src.models import GateResult, OrchestratorState

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# All operational config loaded from Postgres via src.config (after init_config)
from src import config

# Import get_target_slides from renderer (DB-backed)
from src.renderer import get_target_slides


# =============================================================================
# STATE TYPE FOR LANGGRAPH
# =============================================================================

class GraphState(TypedDict):
    """State schema for LangGraph. Must use TypedDict for LangGraph compatibility."""
    # Deck identification
    deck_id: str
    run_id: str
    
    # Generation configuration
    target_slides: int
    max_retries_per_slide: int
    max_total_retries: int
    
    # Current position
    current_intent: Optional[str]
    current_slide_no: int
    
    # Tracking
    prior_titles: list[str]
    generated_slides: list[str]
    failed_intents: list[str]
    abandoned_intents: list[str]  # Intents abandoned due to retry exhaustion
    
    # Retry counters
    slide_retries: int
    total_retries: int
    
    # Current slide state
    current_chunks: list[dict]
    current_draft: Optional[dict]
    current_gate_results: list[dict]  # GateResult as dict for serialization
    
    # Failure info for rewrites
    last_failure_type: Optional[str]  # "format", "grounding", "novelty", "insufficient_context"
    last_failure_details: Optional[dict]
    
    # Completion flags
    is_complete: bool
    error: Optional[str]
    
    # Run metrics
    llm_calls: int
    embeddings_generated: int
    
    # Cost tracking
    prompt_tokens: int       # from LLM calls (actual)
    completion_tokens: int   # from LLM calls (actual)
    embedding_tokens: int    # estimated from text length
    estimated_cost_usd: float
    
    # Image deduplication
    used_image_ids: list[str]  # Images already assigned to slides in this deck
    images_deduplicated: int    # Count of dedup filter hits
    
    # Fallback
    fallback_triggered: bool


def create_initial_state(deck_id: str, run_id: Optional[str] = None) -> GraphState:
    """Create initial state for orchestrator."""
    return {
        "deck_id": deck_id,
        "run_id": run_id or str(uuid4()),
        "target_slides": get_target_slides(),
        "max_retries_per_slide": config.get("max_retries_per_slide", 5),
        "max_total_retries": config.get("max_total_retries", 100),
        "current_intent": None,
        "current_slide_no": 0,
        "prior_titles": [],
        "generated_slides": [],
        "failed_intents": [],
        "abandoned_intents": [],
        "slide_retries": 0,
        "total_retries": 0,
        "current_chunks": [],
        "current_draft": None,
        "current_gate_results": [],
        "last_failure_type": None,
        "last_failure_details": None,
        "is_complete": False,
        "error": None,
        "llm_calls": 0,
        "embeddings_generated": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "embedding_tokens": 0,
        "estimated_cost_usd": 0.0,
        "used_image_ids": [],
        "images_deduplicated": 0,
        "fallback_triggered": False,
    }


def _estimate_embedding_tokens(text: str) -> int:
    """Estimate embedding token count from text (rough cl100k_base ratio)."""
    return int(len(text.split()) * 1.3)


def _calculate_cost(prompt_tokens: int, completion_tokens: int, embedding_tokens: int) -> float:
    """Calculate estimated cost in USD from token counts."""
    return (
        (prompt_tokens / 1000) * config.get("llm_input_cost_per_1k", 0.03)
        + (completion_tokens / 1000) * config.get("llm_output_cost_per_1k", 0.06)
        + (embedding_tokens / 1000) * config.get("embedding_cost_per_1k", 0.00002)
    )


def _accumulate_llm_usage(state: dict, llm_response: LLMResponse) -> dict:
    """Add LLM usage from an LLMResponse to state cost accumulators. Returns updated fields."""
    new_prompt = state.get("prompt_tokens", 0) + llm_response.prompt_tokens
    new_completion = state.get("completion_tokens", 0) + llm_response.completion_tokens
    new_cost = _calculate_cost(new_prompt, new_completion, state.get("embedding_tokens", 0))
    return {
        "prompt_tokens": new_prompt,
        "completion_tokens": new_completion,
        "estimated_cost_usd": new_cost,
    }


def _accumulate_embedding_tokens(state: dict, text: str) -> dict:
    """Add estimated embedding tokens to state. Returns updated fields."""
    estimated = _estimate_embedding_tokens(text)
    new_embedding = state.get("embedding_tokens", 0) + estimated
    new_cost = _calculate_cost(state.get("prompt_tokens", 0), state.get("completion_tokens", 0), new_embedding)
    return {
        "embedding_tokens": new_embedding,
        "estimated_cost_usd": new_cost,
    }


def _get_related_intents(intent: str) -> list[str]:
    """Get related intents for coverage enrichment from the DB-loaded intent map.

    Returns empty list for intents with no related intents configured.
    Replaces the former RELATED_INTENTS hardcoded dict.
    """
    info = INTENT_TYPE_MAP.get(intent)
    return list(info.related_intents) if info else []


async def _start_generation_run(deck_id: str, config: dict) -> str:
    """INSERT a generation_run row and return the DB-generated run_id.

    Uses RETURNING to get the UUID assigned by gen_random_uuid().
    Falls back to Python uuid4() if the INSERT fails — generation
    must not be blocked by tracking infrastructure.
    """
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                "INSERT INTO generation_run (deck_id, config) "
                "VALUES ($1, $2::jsonb) RETURNING run_id::text",
                UUID(deck_id),
                json.dumps(config),
            )
            run_id = row["run_id"]
            logger.info(f"[run_lifecycle] Created generation_run: {run_id}")
            return run_id
    except Exception as e:
        fallback_id = str(uuid4())
        logger.warning(f"[run_lifecycle] Failed to create generation_run: {e}. Using fallback run_id={fallback_id}")
        return fallback_id


async def _complete_generation_run(run_id: str, final_state: dict, status: str = "completed") -> None:
    """UPDATE generation_run with final metrics and status.

    Called on both success and failure. The status parameter determines
    the run_status enum value.
    """
    try:
        async with get_connection() as conn:
            await conn.execute(
                "UPDATE generation_run SET "
                "status = $2::run_status, "
                "completed_at = now(), "
                "slides_generated = $3, "
                "slides_failed = $4, "
                "total_retries = $5, "
                "llm_calls = $6, "
                "prompt_tokens = $7, "
                "completion_tokens = $8, "
                "embedding_tokens = $9, "
                "estimated_cost_usd = $10, "
                "error_message = $11 "
                "WHERE run_id = $1",
                UUID(run_id),
                status,
                len(final_state.get("generated_slides", [])),
                len(final_state.get("failed_intents", [])) + len(final_state.get("abandoned_intents", [])),
                final_state.get("total_retries", 0),
                final_state.get("llm_calls", 0),
                final_state.get("prompt_tokens", 0),
                final_state.get("completion_tokens", 0),
                final_state.get("embedding_tokens", 0),
                final_state.get("estimated_cost_usd", 0.0),
                final_state.get("error"),
            )
            logger.info(f"[run_lifecycle] Updated generation_run {run_id}: status={status}")
    except Exception as e:
        logger.warning(f"[run_lifecycle] Failed to update generation_run {run_id}: {e}")


def _build_run_config() -> dict:
    """Build the config JSONB snapshot for generation_run.

    Captures the runtime configuration so runs are reproducible.
    """
    return {
        "max_retries_per_slide": config.get("max_retries_per_slide", 5),
        "max_total_retries": config.get("max_total_retries", 100),
        "max_llm_calls": config.get("max_llm_calls", 200),
        "grounding_threshold": config.get("grounding_threshold", 0.3),
        "grounding_threshold_diagram": config.get("grounding_threshold_diagram", 0.2),
        "novelty_threshold": config.get("novelty_threshold", 0.85),
        "cost_limit_usd": config.get("cost_limit_usd", 10.00),
        "image_selection_enabled": config.get("image_selection_enabled", False),
        "image_min_score": config.get("image_min_score", 0.5),
    }


def _determine_run_status(final_state: dict) -> str:
    """Determine the run_status enum value from final orchestrator state."""
    if final_state.get("estimated_cost_usd", 0) > config.get("cost_limit_usd", 10.00):
        return "cost_limited"
    total_failures = len(final_state.get("failed_intents", [])) + len(final_state.get("abandoned_intents", []))
    if total_failures > config.get("max_failed_intents", 3):
        return "failed"
    if final_state.get("total_retries", 0) >= config.get("max_total_retries", 100):
        return "failed"
    if final_state.get("llm_calls", 0) >= config.get("max_llm_calls", 200):
        return "failed"
    if final_state.get("is_complete"):
        return "completed"
    return "failed"


async def _set_deck_status(deck_id: str, status: str) -> None:
    """Update deck.status. Swallows errors to avoid blocking generation."""
    try:
        async with get_connection() as conn:
            await conn.execute(
                "UPDATE deck SET status = $2::deck_status WHERE deck_id = $1",
                UUID(deck_id),
                status,
            )
            logger.info(f"[deck_status] Set deck {deck_id} status={status}")
    except Exception as e:
        logger.warning(f"[deck_status] Failed to set deck {deck_id} status={status}: {e}")


async def cleanup_stale_generating(max_age_hours: int = 1) -> int:
    """Reset decks stuck in 'generating' state for more than max_age_hours.

    Called once at startup. Returns the count of decks reset.
    Also marks any orphaned generation_run rows as 'failed'.
    """
    try:
        async with get_connection() as conn:
            deck_count = await conn.fetchval(
                "WITH updated AS ("
                "  UPDATE deck SET status = 'failed' "
                "  WHERE status = 'generating' "
                "  AND updated_at < now() - make_interval(hours => $1) "
                "  RETURNING 1"
                ") SELECT count(*) FROM updated",
                max_age_hours,
            )

            run_count = await conn.fetchval(
                "WITH updated AS ("
                "  UPDATE generation_run SET status = 'failed', "
                "  completed_at = now(), error_message = 'Stale run reset at startup' "
                "  WHERE status = 'running' "
                "  AND started_at < now() - make_interval(hours => $1) "
                "  RETURNING 1"
                ") SELECT count(*) FROM updated",
                max_age_hours,
            )

            if deck_count > 0 or run_count > 0:
                logger.warning(
                    f"[cleanup] Reset {deck_count} stale decks and {run_count} stale runs "
                    f"(older than {max_age_hours}h)"
                )
            return deck_count
    except Exception as e:
        logger.warning(f"[cleanup] Stale run cleanup failed: {e}")
        return 0


# =============================================================================
# NODE IMPLEMENTATIONS
# =============================================================================

async def pick_intent_node(state: GraphState) -> GraphState:
    """
    Pick the next intent to generate.
    
    Uses fn_pick_next_intent() to deterministically select the next
    missing intent based on canonical ordering.
    Also tracks abandoned intents (retry exhaustion) and skips them.
    """
    logger.info(f"[pick_intent] Picking next intent for deck {state['deck_id']}")
    
    new_state = {**state}
    
    # Check if the previous intent was abandoned due to retry exhaustion
    current = state.get("current_intent")
    abandoned = list(state.get("abandoned_intents", []))
    if (current
        and current not in state.get("generated_slides", [])
        and current not in abandoned
        and state.get("slide_retries", 0) >= state.get("max_retries_per_slide", 5)):
        abandoned = abandoned + [current]
        new_state["abandoned_intents"] = abandoned
        logger.warning(f"[pick_intent] Abandoned intent: {current}")
    
    # Pick next intent, excluding abandoned ones via DB-side filter
    intent = await tool_call("mcp_pick_next_intent", deck_id=state["deck_id"], exclude=abandoned)
    if intent:
        logger.info(f"[pick_intent] DB returned intent: {intent} (excluded {len(abandoned)} abandoned)")
    
    if intent is None:
        logger.info("[pick_intent] All intents covered - deck complete")
        return {
            **new_state,
            "is_complete": True,
            "current_intent": None,
        }
    
    # Determine slide number (count existing + 1)
    slide_no = len(state["generated_slides"]) + 1
    
    logger.info(f"[pick_intent] Next intent: {intent}, slide_no: {slide_no}")
    
    return {
        **new_state,
        "current_intent": intent,
        "current_slide_no": slide_no,
        "slide_retries": 0,
        "current_chunks": [],
        "current_draft": None,
        "current_gate_results": [],
        "last_failure_type": None,
        "last_failure_details": None,
    }


async def _log_gate_result(state: GraphState, gate_result: dict):
    """Persist a gate check result to gate_log via fn_log_gate."""
    try:
        await tool_call(
            "mcp_log_gate",
            run_id=state["run_id"],
            deck_id=state["deck_id"],
            slide_no=state["current_slide_no"],
            gate_name=gate_result["gate_name"],
            decision="pass" if gate_result["passed"] else "fail",
            score=gate_result.get("score"),
            threshold=gate_result.get("threshold"),
            reason="; ".join(gate_result.get("errors", [])) or None,
            payload=gate_result.get("details"),
        )
    except Exception as e:
        logger.warning(f"Failed to log gate result: {e}")


async def retrieve_node(state: GraphState) -> GraphState:
    """
    Retrieve relevant chunks for the current intent.
    
    Uses fn_hybrid_search() with query derived from intent metadata.
    Enriches query with coverage data from v_deck_coverage (Views as Sensors).
    """
    intent = state["current_intent"]
    logger.info(f"[retrieve] Retrieving chunks for intent: {intent}")
    
    # Build query from intent metadata
    metadata = get_intent_metadata(intent)
    query = f"{metadata['suggested_title']} {metadata['requirements']}"
    
    # If we have failure details with alternative query, use it
    if state.get("last_failure_type") == "insufficient_context":
        alt_queries = state.get("last_failure_details", {}).get("alternative_queries", [])
        if alt_queries:
            query = alt_queries[0]
            logger.info(f"[retrieve] Using alternative query: {query}")
    
    # --- Coverage Enrichment (Views as Active Agent Sensors) ---
    enrichment_text = ""
    try:
        deck_state = await tool_call("mcp_get_deck_state", deck_id=state["deck_id"])
        coverage = deck_state.get("coverage") or {}
        covered = set(coverage.get("covered") or [])
        related = _get_related_intents(intent)
        overlap = covered & set(related)
        if overlap:
            enrichment_text = f" (differentiate from: {', '.join(overlap)})"
            query += enrichment_text
            logger.info(f"[retrieve] Coverage enrichment applied: {enrichment_text}")
    except Exception as e:
        logger.warning(f"[retrieve] Coverage enrichment skipped: {e}")
    
    # Search for relevant chunks
    chunks = await tool_call(
        "mcp_search_chunks",
        query=query,
        top_k=config.get("default_top_k", 10),
        semantic_weight=config.get("semantic_weight", 0.7),
        lexical_weight=config.get("lexical_weight", 0.3),
    )
    
    logger.info(f"[retrieve] Found {len(chunks)} chunks")
    if chunks and logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"[retrieve] chunk[0] type={type(chunks[0]).__name__}, keys={list(chunks[0].keys()) if isinstance(chunks[0], dict) else 'N/A'}")
    
    # Estimate embedding cost for the query
    new_state = {**state}
    emb_update = _accumulate_embedding_tokens(new_state, query)
    new_state.update(emb_update)
    
    # G1 Gate: Check retrieval quality (PL/pgSQL via MCP)
    g1_result = await tool_call(
        "mcp_check_retrieval_quality",
        search_results=chunks,
        min_chunks=config.get("g1_min_chunks", 3),
        min_score=config.get("g1_min_score", 0.3),
    )
    
    gate_result = {
        "gate_name": "g1_retrieval",
        "passed": g1_result["is_valid"],
        "score": g1_result.get("top_score", 0.0),
        "errors": g1_result.get("errors", []),
        "details": {"chunk_count": g1_result.get("chunk_count", 0), "enrichment": enrichment_text},
    }
    
    # Log coverage sensor reading
    coverage_gate = {
        "gate_name": "coverage_sensor",
        "passed": True,
        "score": 1.0,
        "errors": [],
        "details": {
            "covered": list(covered) if 'covered' in dir() else [],
            "enrichment_applied": enrichment_text,
        },
    }
    
    new_state["current_chunks"] = chunks
    new_state["current_gate_results"] = [gate_result, coverage_gate]
    
    await _log_gate_result(new_state, gate_result)
    await _log_gate_result(new_state, coverage_gate)
    
    return new_state


async def draft_node(state: GraphState) -> GraphState:
    """
    Draft a slide using GPT-4.
    
    Uses prompt templates from PROMPT_TEMPLATES.md.
    Handles rewrite scenarios based on last_failure_type.
    Accumulates LLM token usage for cost tracking.
    """
    intent = state["current_intent"]
    chunks = state["current_chunks"]
    slide_no = state["current_slide_no"]
    
    logger.info(f"[draft] Drafting slide for intent: {intent} (attempt {state.get('slide_retries', 0) + 1})")
    
    new_state = {**state}
    new_state["llm_calls"] = state.get("llm_calls", 0) + 1
    
    try:
        # Determine if this is a rewrite
        failure_type = state.get("last_failure_type")
        failure_details = state.get("last_failure_details", {})
        
        if failure_type == "format" and state.get("current_draft"):
            # Rewrite for format errors
            draft, llm_resp = await rewrite_slide_format(
                failed_slide_spec=state["current_draft"],
                validation_errors=failure_details.get("errors", []),
                original_chunks=chunks,
            )
        elif failure_type == "grounding" and state.get("current_draft"):
            # Rewrite for grounding errors
            draft, llm_resp = await rewrite_slide_grounding(
                failed_slide_spec=state["current_draft"],
                ungrounded_bullets=failure_details.get("ungrounded_bullets", []),
                cited_chunks=chunks,
            )
        elif failure_type == "novelty" and state.get("current_draft"):
            # Rewrite for novelty errors
            draft, llm_resp = await rewrite_slide_novelty(
                failed_slide_spec=state["current_draft"],
                most_similar_slide=failure_details.get("most_similar_slide", {}),
                similarity_score=failure_details.get("similarity_score", 0.0),
                chunks=chunks,
            )
        else:
            # Fresh draft
            draft, llm_resp = await draft_slide(
                intent=intent,
                chunks=chunks,
                slide_no=slide_no,
                total_slides=state.get("target_slides", get_target_slides()),
                prior_titles=state.get("prior_titles", []),
            )
        
        # Accumulate LLM usage for cost tracking
        cost_update = _accumulate_llm_usage(new_state, llm_resp)
        new_state.update(cost_update)
        
        logger.info(f"[draft] Draft generated: {draft.get('title', 'No title')}")
        
        # Ensure intent is the correct enum value (LLM may return wrong value)
        draft["intent"] = intent
        
        new_state["current_draft"] = draft
        new_state["last_failure_type"] = None
        new_state["last_failure_details"] = None
        
        return new_state
        
    except InsufficientContextError as e:
        logger.warning(f"[draft] Insufficient context: {e.missing}")
        
        # Generate alternative queries for next retrieval attempt
        alt_queries, alt_llm_resp = await generate_alternative_queries(intent, e.missing)
        new_state["llm_calls"] = new_state["llm_calls"] + 1
        
        # Accumulate usage from alt queries call
        cost_update = _accumulate_llm_usage(new_state, alt_llm_resp)
        new_state.update(cost_update)
        
        new_state["last_failure_type"] = "insufficient_context"
        new_state["last_failure_details"] = {
            "missing": e.missing,
            "alternative_queries": alt_queries,
        }
        new_state["slide_retries"] = state.get("slide_retries", 0) + 1
        new_state["total_retries"] = state.get("total_retries", 0) + 1
        
        return new_state
        
    except ParseError as e:
        logger.error(f"[draft] Parse error: {e.error}")
        
        new_state["last_failure_type"] = "parse_error"
        new_state["last_failure_details"] = {"error": e.error, "raw": e.raw_response[:500]}
        new_state["slide_retries"] = state.get("slide_retries", 0) + 1
        new_state["total_retries"] = state.get("total_retries", 0) + 1
        
        return new_state
        
    except LLMError as e:
        logger.error(f"[draft] LLM error: {e}")
        
        new_state["last_failure_type"] = "llm_error"
        new_state["last_failure_details"] = {"error": str(e)}
        new_state["slide_retries"] = state.get("slide_retries", 0) + 1
        new_state["total_retries"] = state.get("total_retries", 0) + 1
        
        return new_state


async def validate_format_node(state: GraphState) -> GraphState:
    """
    Validate slide format (Gate G3).
    
    Checks required fields, bullet count, bullet length.
    """
    draft = state["current_draft"]
    logger.info(f"[validate_format] Checking format for: {draft.get('title', 'No title')}")
    
    result = await tool_call("mcp_validate_slide_structure", slide_spec=draft)
    
    gate_result = {
        "gate_name": "g3_format",
        "passed": result["is_valid"],
        "score": 1.0 if result["is_valid"] else 0.0,
        "errors": result.get("errors", []),
        "details": None,
    }
    
    new_state = {**state}
    new_state["current_gate_results"] = state["current_gate_results"] + [gate_result]
    
    if not result["is_valid"]:
        new_state["last_failure_type"] = "format"
        new_state["last_failure_details"] = {"errors": result["errors"]}
        new_state["slide_retries"] = state["slide_retries"] + 1
        new_state["total_retries"] = state["total_retries"] + 1
    
    if result["is_valid"]:
        logger.info(f"[validate_format] G3 passed: True")
    else:
        logger.warning(f"[validate_format] G3 FAILED: {result['errors']}")
    
    await _log_gate_result(new_state, gate_result)
    
    return new_state


async def validate_citations_node(state: GraphState) -> GraphState:
    """
    Validate slide citations (Gate G2).
    
    Checks that citations reference real chunks in the database.
    """
    draft = state["current_draft"]
    logger.info(f"[validate_citations] Checking citations for: {draft.get('title', 'No title')}")
    
    result = await tool_call("mcp_validate_citations", slide_spec=draft)
    
    gate_result = {
        "gate_name": "g2_citation",
        "passed": result["is_valid"],
        "score": result.get("citation_count", 0) / max(len(draft.get("citations", [])), 1),
        "errors": result.get("errors", []),
        "details": {"citation_count": result.get("citation_count", 0)},
    }
    
    new_state = {**state}
    new_state["current_gate_results"] = state["current_gate_results"] + [gate_result]
    
    if not result["is_valid"]:
        new_state["last_failure_type"] = "citations"
        new_state["last_failure_details"] = {"errors": result["errors"]}
        new_state["slide_retries"] = state["slide_retries"] + 1
        new_state["total_retries"] = state["total_retries"] + 1
    
    logger.info(f"[validate_citations] G2 passed: {result['is_valid']}")
    
    await _log_gate_result(new_state, gate_result)
    
    return new_state


async def check_grounding_node(state: GraphState) -> GraphState:
    """
    Check semantic grounding of bullets (Gate G2.5).
    
    Verifies each bullet is semantically similar to cited chunks.
    """
    draft = state["current_draft"]
    logger.info(f"[check_grounding] Checking grounding for: {draft.get('title', 'No title')}")
    
    text_segments = extract_slide_text(draft)
    new_state = {**state}
    new_state["embeddings_generated"] = state.get("embeddings_generated", 0) + len(text_segments)
    
    for segment in text_segments:
        emb_update = _accumulate_embedding_tokens(new_state, segment)
        new_state.update(emb_update)
    
    # Diagram/flow slides use short callouts that don't embed well against
    # longer source chunks, so they need a lower grounding threshold.
    slide_type = draft.get("slide_type", "bullets")
    if slide_type in ("diagram", "flow"):
        threshold = config.get("grounding_threshold_diagram", 0.2)
    else:
        threshold = config.get("grounding_threshold", 0.3)
    
    result = await tool_call("mcp_check_grounding", slide_spec=draft, threshold=threshold, run_id=state["run_id"])
    
    gate_result = {
        "gate_name": "g2.5_grounding",
        "passed": result["is_grounded"],
        "score": result.get("min_similarity", 0.0),
        "threshold": threshold,
        "errors": [f"Ungrounded bullets: {result.get('ungrounded_bullets', [])}"] if not result["is_grounded"] else [],
        "details": result.get("grounding_details"),
    }
    
    new_state["current_gate_results"] = state["current_gate_results"] + [gate_result]
    
    if not result["is_grounded"]:
        new_state["last_failure_type"] = "grounding"
        new_state["last_failure_details"] = {
            "ungrounded_bullets": result.get("ungrounded_bullets", []),
            "min_similarity": result.get("min_similarity", 0.0),
        }
        new_state["slide_retries"] = state["slide_retries"] + 1
        new_state["total_retries"] = state["total_retries"] + 1
    
    logger.info(f"[check_grounding] G2.5 passed: {result['is_grounded']}, min_sim: {result.get('min_similarity', 0):.3f}")
    
    await _log_gate_result(new_state, gate_result)
    
    return new_state


async def check_novelty_node(state: GraphState) -> GraphState:
    """
    Check content novelty (Gate G4).
    
    Ensures slide content is not too similar to existing slides.
    """
    draft = state["current_draft"]
    deck_id = state["deck_id"]
    
    logger.info(f"[check_novelty] Checking novelty for: {draft.get('title', 'No title')}")
    
    text_segments = extract_slide_text(draft)
    candidate_text = " ".join([
        draft.get("title", ""),
        " ".join(text_segments),
        draft.get("speaker_notes", "") or "",
    ])
    
    new_state = {**state}
    new_state["embeddings_generated"] = state.get("embeddings_generated", 0) + 1
    
    # Estimate embedding cost for candidate text
    emb_update = _accumulate_embedding_tokens(new_state, candidate_text)
    new_state.update(emb_update)
    
    novelty_threshold = config.get("novelty_threshold", 0.85)
    result = await tool_call("mcp_check_novelty", deck_id=deck_id, candidate_text=candidate_text, threshold=novelty_threshold)
    
    gate_result = {
        "gate_name": "g4_novelty",
        "passed": result["is_novel"],
        "score": result.get("max_similarity", 0.0),
        "threshold": novelty_threshold,
        "errors": [f"Too similar to slide {result.get('most_similar_slide_no')} ({result.get('most_similar_intent')})"] if not result["is_novel"] else [],
        "details": {
            "max_similarity": result.get("max_similarity"),
            "most_similar_slide_no": result.get("most_similar_slide_no"),
            "most_similar_intent": result.get("most_similar_intent"),
        },
    }
    
    new_state["current_gate_results"] = state["current_gate_results"] + [gate_result]
    
    if not result["is_novel"]:
        new_state["last_failure_type"] = "novelty"
        new_state["last_failure_details"] = {
            "similarity_score": result.get("max_similarity", 0.0),
            "most_similar_slide": {},  # Would need to fetch the actual slide
        }
        new_state["slide_retries"] = state["slide_retries"] + 1
        new_state["total_retries"] = state["total_retries"] + 1
    
    logger.info(f"[check_novelty] G4 passed: {result['is_novel']}, max_sim: {result.get('max_similarity', 0):.3f}")
    
    await _log_gate_result(new_state, gate_result)
    
    return new_state


async def select_image_node(state: GraphState) -> GraphState:
    """
    Optionally select an image for the slide.
    
    Skips if IMAGE_SELECTION_ENABLED=false.
    Filters out images already assigned to earlier slides in this deck.
    G5 gate always passes (image is optional) - logs result either way.
    """
    if not config.get("image_selection_enabled", False):
        return state  # Skip entirely

    intent = state.get("current_intent", "")
    if not should_select_image(intent):
        logger.info(f"[select_image] Skipping image for intent={intent} (require_image=false)")
        return state

    draft = state["current_draft"]
    
    logger.info(f"[select_image] Searching for image for: {draft.get('title', 'No title')}")
    
    text_segments = extract_slide_text(draft)
    query = f"{draft.get('title', '')} {' '.join(text_segments)}"
    
    # Build filters from style preference
    filters = {}
    style_pref = config.get("image_style_preference", [])
    if style_pref and style_pref[0]:
        filters["style"] = style_pref[0]
    
    # Search for images (bumped from 3 to 10 for dedup headroom)
    try:
        candidates = await tool_call(
            "mcp_search_images",
            query=query,
            filters=filters if filters else None,
            top_k=config.get("default_top_k", 10),
        )
    except Exception as e:
        logger.warning(f"[select_image] Image search failed: {e}")
        candidates = []
    
    # Tag candidates whose use_cases match the slide intent
    intent = state.get("current_intent", "")
    for c in candidates:
        c["intent_boosted"] = bool(intent and intent in c.get("use_cases", []))

    # Filter out already-used images (hard dedup)
    used = set(state["used_image_ids"])
    pre_filter_count = len(candidates)
    candidates = [c for c in candidates if c["image_id"] not in used]
    deduped_count = pre_filter_count - len(candidates)

    # Apply recency penalty: recently-selected images from the ordered list
    # get a score reduction to promote variety across the deck
    used_ordered = state["used_image_ids"]
    for c in candidates:
        recency_penalty = 0.0
        img_id = c["image_id"]
        if img_id in used_ordered:
            position_from_end = len(used_ordered) - used_ordered.index(img_id)
            if position_from_end == 1:
                recency_penalty = 0.10
            elif position_from_end <= 3:
                recency_penalty = 0.05
        c["adjusted_score"] = c["similarity"] - recency_penalty

    # Split into intent-matched and others
    intent_pool = [c for c in candidates if c["intent_boosted"]]
    other_pool  = [c for c in candidates if not c["intent_boosted"]]

    boosted_count = len(intent_pool)
    if boosted_count:
        logger.info(f"[select_image] Intent pool: {boosted_count} candidates matched intent '{intent}'")

    if deduped_count > 0:
        logger.info(f"[select_image] Filtered {deduped_count} already-used images, {len(candidates)} remaining")
    
    selected_image_id = None
    g5_passed = True  # G5 always passes - image is optional
    g5_details = {
        "intent": intent,
        "intent_pool_size": boosted_count,
        "candidates_found": pre_filter_count,
        "candidates_after_dedup": len(candidates),
        "deduped_count": deduped_count,
    }
    
    # Selection strategy:
    #   1. If intent-matched images exist, weighted-random pick from that pool
    #      (similarity scores as weights → higher-scoring images are more likely
    #       but lower-scoring ones can still win → variety across runs)
    #   2. Otherwise fall back to top semantic match from the full pool
    top_candidate = None
    selection_method = None

    if intent_pool:
        viable = [c for c in intent_pool if c.get("adjusted_score", c["similarity"]) >= config.get("image_intent_min_score", 0.35)]
        if viable:
            weights = [max(c.get("adjusted_score", c["similarity"]), 0.01) for c in viable]
            top_candidate = random.choices(viable, weights=weights, k=1)[0]
            selection_method = "intent_weighted_random"
    
    if top_candidate is None and candidates:
        candidates.sort(key=lambda c: c.get("adjusted_score", c["similarity"]), reverse=True)
        if candidates[0].get("adjusted_score", candidates[0]["similarity"]) >= config.get("image_min_score", 0.5):
            top_candidate = candidates[0]
            selection_method = "semantic_top"
    
    if top_candidate is not None:
        # Validate via G5
        try:
            validation = await tool_call("mcp_validate_image", image_id=top_candidate["image_id"])
        except Exception as e:
            logger.warning(f"[select_image] Image validation failed: {e}")
            validation = {"is_valid": False, "errors": [str(e)]}
        
        if validation["is_valid"]:
            selected_image_id = top_candidate["image_id"]
            g5_details["selected"] = top_candidate["image_id"]
            g5_details["score"] = top_candidate["similarity"]
            g5_details["selection_method"] = selection_method
            g5_details["intent_boosted"] = top_candidate.get("intent_boosted", False)
            logger.info(
                f"[select_image] Selected image: {selected_image_id} "
                f"(score: {top_candidate['similarity']:.3f}, method: {selection_method})"
            )
        else:
            g5_details["validation_errors"] = validation["errors"]
            logger.info(f"[select_image] Top candidate failed validation: {validation['errors']}")
    else:
        g5_details["reason"] = "No suitable image found above threshold"
        logger.info(f"[select_image] No suitable image found (min_score: {config.get('image_min_score', 0.5)})")
    
    # Log G5 gate (always passes, records selection decision)
    gate_result = {
        "gate_name": "g5_image",
        "passed": g5_passed,
        "score": candidates[0]["similarity"] if candidates else 0.0,
        "errors": [],
        "details": g5_details,
    }
    
    # Update draft with image_id if selected
    new_state = {**state}
    new_state["images_deduplicated"] = state["images_deduplicated"] + deduped_count
    
    if selected_image_id:
        new_state["current_draft"] = {**draft, "image_id": selected_image_id}
        # Track image at selection time (not commit time) to prevent races
        new_state["used_image_ids"] = state["used_image_ids"] + [selected_image_id]
    
    new_state["current_gate_results"] = state["current_gate_results"] + [gate_result]
    
    return new_state


async def commit_node(state: GraphState) -> GraphState:
    """
    Commit the slide to the database (Gate G5).
    
    Passes novelty and grounding results to commit function for gate logging.
    """
    draft = state["current_draft"]
    deck_id = state["deck_id"]
    slide_no = state["current_slide_no"]
    run_id = state["run_id"]
    
    logger.info(f"[commit] Committing slide {slide_no}: {draft.get('title', 'No title')}")
    
    # Extract gate results
    novelty_result = next(
        (g for g in state["current_gate_results"] if g["gate_name"] == "g4_novelty"),
        None
    )
    grounding_result = next(
        (g for g in state["current_gate_results"] if g["gate_name"] == "g2.5_grounding"),
        None
    )
    
    result = await tool_call(
        "mcp_commit_slide",
        deck_id=deck_id,
        slide_no=slide_no,
        slide_spec=draft,
        run_id=run_id,
        novelty_passed=novelty_result["passed"] if novelty_result else None,
        novelty_score=novelty_result["details"].get("max_similarity") if novelty_result else None,
        grounding_passed=grounding_result["passed"] if grounding_result else None,
        grounding_score=grounding_result["score"] if grounding_result else None,
        image_id=draft.get("image_id"),
        draft_retries=state["slide_retries"],
    )
    
    gate_result = {
        "gate_name": "g5_commit",
        "passed": result["success"],
        "score": 1.0 if result["success"] else 0.0,
        "errors": result.get("errors", []),
        "details": {"slide_id": result.get("slide_id")},
    }
    
    new_state = {**state}
    new_state["current_gate_results"] = state["current_gate_results"] + [gate_result]
    
    if result["success"]:
        new_state["generated_slides"] = state["generated_slides"] + [state["current_intent"]]
        new_state["prior_titles"] = state["prior_titles"] + [draft.get("title", "")]
        logger.info(f"[commit] Slide committed successfully: {result.get('slide_id')}")
    else:
        logger.error(f"[commit] Commit failed: {result.get('errors')}")
        new_state["failed_intents"] = state["failed_intents"] + [state["current_intent"]]
    
    return new_state


# =============================================================================
# CONDITIONAL EDGES
# =============================================================================

def should_continue_after_pick_intent(state: GraphState) -> str:
    """Determine next step after pick_intent."""
    if state["is_complete"]:
        return "end"
    if state["current_intent"] is None:
        return "end"
    return "retrieve"


def should_continue_after_retrieve(state: GraphState) -> str:
    """Determine next step after retrieve."""
    g1_result = next(
        (g for g in state["current_gate_results"] if g["gate_name"] == "g1_retrieval"),
        None
    )
    
    if g1_result and not g1_result["passed"]:
        if state["slide_retries"] < state["max_retries_per_slide"]:
            return "draft"
        return "pick_intent"
    
    return "draft"


def should_continue_after_draft(state: GraphState) -> str:
    """Determine next step after draft."""
    # Check for failure
    failure_type = state.get("last_failure_type")
    
    if failure_type == "insufficient_context":
        # Need to re-retrieve with new query
        if state["slide_retries"] < state["max_retries_per_slide"]:
            return "retrieve"
        return "pick_intent"  # Give up
    
    if failure_type in ("parse_error", "llm_error"):
        # Simple retry
        if state["slide_retries"] < state["max_retries_per_slide"]:
            return "draft"
        return "pick_intent"  # Give up
    
    if state["current_draft"] is None:
        # No draft produced
        if state["slide_retries"] < state["max_retries_per_slide"]:
            return "draft"
        return "pick_intent"
    
    return "validate_format"


def should_continue_after_format(state: GraphState) -> str:
    """Determine next step after format validation."""
    # Get the LAST G3 result (most recent)
    g3_results = [g for g in state["current_gate_results"] if g["gate_name"] == "g3_format"]
    g3_result = g3_results[-1] if g3_results else None
    
    if g3_result and not g3_result["passed"]:
        if state["slide_retries"] < state["max_retries_per_slide"]:
            return "draft"  # Rewrite to fix format
        return "pick_intent"  # Give up
    
    return "validate_citations"


def should_continue_after_citations(state: GraphState) -> str:
    """Determine next step after citation validation."""
    # Get the LAST G2 result (most recent)
    g2_results = [g for g in state["current_gate_results"] if g["gate_name"] == "g2_citation"]
    g2_result = g2_results[-1] if g2_results else None
    
    if g2_result and not g2_result["passed"]:
        if state["slide_retries"] < state["max_retries_per_slide"]:
            return "draft"  # Rewrite to fix citations
        return "pick_intent"  # Give up
    
    return "check_grounding"


def should_continue_after_grounding(state: GraphState) -> str:
    """Determine next step after grounding check."""
    # Get the LAST G2.5 result (most recent)
    g25_results = [g for g in state["current_gate_results"] if g["gate_name"] == "g2.5_grounding"]
    g25_result = g25_results[-1] if g25_results else None
    
    if g25_result and not g25_result["passed"]:
        if state["slide_retries"] < state["max_retries_per_slide"]:
            return "draft"  # Rewrite to fix grounding
        return "pick_intent"  # Give up
    
    return "check_novelty"


def should_continue_after_novelty(state: GraphState) -> str:
    """Determine next step after novelty check."""
    # Get the LAST G4 result (most recent)
    g4_results = [g for g in state["current_gate_results"] if g["gate_name"] == "g4_novelty"]
    g4_result = g4_results[-1] if g4_results else None
    
    if g4_result and not g4_result["passed"]:
        if state["slide_retries"] < state["max_retries_per_slide"]:
            return "draft"  # Rewrite with different angle
        return "pick_intent"  # Give up
    
    return "select_image"


def should_continue_after_select_image(state: GraphState) -> str:
    """Determine next step after image selection. Always proceeds to commit."""
    return "commit"


def should_continue_after_commit(state: GraphState) -> str:
    """Determine next step after commit."""
    # Check cost limit
    if state.get("estimated_cost_usd", 0) > config.get("cost_limit_usd", 10.00):
        logger.warning(f"[orchestrator] Cost limit exceeded: ${state['estimated_cost_usd']:.2f}")
        return "end"
    
    # Check total retries limit
    if state.get("total_retries", 0) >= state.get("max_total_retries", config.get("max_total_retries", 100)):
        logger.warning(f"[orchestrator] Max total retries reached ({state['total_retries']})")
        return "end"
    
    # Check LLM calls limit
    if state.get("llm_calls", 0) >= config.get("max_llm_calls", 200):
        logger.warning(f"[orchestrator] Max LLM calls reached ({state['llm_calls']})")
        return "end"
    
    # Check fallback threshold (failed + abandoned > max_failed_intents)
    total_failures = len(state.get("failed_intents", [])) + len(state.get("abandoned_intents", []))
    if total_failures > config.get("max_failed_intents", 3):
        logger.warning(f"[orchestrator] Fallback triggered: {total_failures} failed/abandoned intents")
        return "end"
    
    return "pick_intent"


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_orchestrator_graph() -> StateGraph:
    """Build the LangGraph state machine for slide generation."""
    
    # Create graph
    graph = StateGraph(GraphState)
    
    # Add nodes
    graph.add_node("pick_intent", pick_intent_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("draft", draft_node)
    graph.add_node("validate_format", validate_format_node)
    graph.add_node("validate_citations", validate_citations_node)
    graph.add_node("check_grounding", check_grounding_node)
    graph.add_node("check_novelty", check_novelty_node)
    graph.add_node("select_image", select_image_node)
    graph.add_node("commit", commit_node)
    
    # Set entry point
    graph.set_entry_point("pick_intent")
    
    # Add conditional edges
    graph.add_conditional_edges(
        "pick_intent",
        should_continue_after_pick_intent,
        {"retrieve": "retrieve", "end": END}
    )
    
    graph.add_conditional_edges(
        "retrieve",
        should_continue_after_retrieve,
        {"draft": "draft", "pick_intent": "pick_intent"}
    )
    
    graph.add_conditional_edges(
        "draft",
        should_continue_after_draft,
        {"validate_format": "validate_format", "retrieve": "retrieve", "draft": "draft", "pick_intent": "pick_intent"}
    )
    
    graph.add_conditional_edges(
        "validate_format",
        should_continue_after_format,
        {"validate_citations": "validate_citations", "draft": "draft", "pick_intent": "pick_intent"}
    )
    
    graph.add_conditional_edges(
        "validate_citations",
        should_continue_after_citations,
        {"check_grounding": "check_grounding", "draft": "draft", "pick_intent": "pick_intent"}
    )
    
    graph.add_conditional_edges(
        "check_grounding",
        should_continue_after_grounding,
        {"check_novelty": "check_novelty", "draft": "draft", "pick_intent": "pick_intent"}
    )
    
    graph.add_conditional_edges(
        "check_novelty",
        should_continue_after_novelty,
        {"select_image": "select_image", "draft": "draft", "pick_intent": "pick_intent"}
    )
    
    graph.add_conditional_edges(
        "select_image",
        should_continue_after_select_image,
        {"commit": "commit"}
    )
    
    graph.add_conditional_edges(
        "commit",
        should_continue_after_commit,
        {"pick_intent": "pick_intent", "end": END}
    )
    
    return graph


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

def _wrap_node_with_progress(node_spec, node_name, progress_queue):
    """Wrap a graph node's runnable to push progress events before execution.
    
    LangGraph 1.0.7 stores nodes as StateNodeSpec objects with a .runnable
    attribute. We wrap the runnable's ainvoke to inject progress events,
    preserving the full StateNodeSpec (ends, retry_policy, etc.).
    """
    from langgraph._internal._runnable import RunnableCallable

    original_runnable = node_spec.runnable

    async def wrapped_fn(state):
        if progress_queue:
            await progress_queue.put({
                "type": "progress",
                "deck_id": state.get("deck_id"),
                "phase": node_name,
                "intent": state.get("current_intent"),
                "slides_ready": len(state.get("generated_slides", [])),
                "cost_usd": state.get("estimated_cost_usd", 0.0),
            })
        try:
            result = await original_runnable.ainvoke(state)
        except Exception:
            logger.error(f"[progress-wrap] {node_name} raised exception", exc_info=True)
            raise

        if progress_queue:
            old_gates = state.get("current_gate_results") or []
            new_gates = (result.get("current_gate_results") or []) if isinstance(result, dict) else []
            for gate in new_gates[len(old_gates):]:
                event = {
                    "type": "gate_update",
                    "deck_id": state.get("deck_id"),
                    "gate_name": gate.get("gate_name", ""),
                    "decision": "pass" if gate.get("passed") else "fail",
                    "score": gate.get("score", 0),
                    "slide_no": result.get("current_slide_no", 0),
                }
                details = gate.get("details") or {}
                if "chunk_count" in details:
                    event["chunk_count"] = details["chunk_count"]
                await progress_queue.put(event)

        return result

    node_spec.runnable = RunnableCallable(func=wrapped_fn, afunc=wrapped_fn)
    return node_spec


async def run_generation_headless(
    deck_id: str,
    topic: Optional[str] = None,
    target_slides: int | None = None,
    progress_queue: Optional[asyncio.Queue] = None,
) -> dict:
    """
    Run generation without managing pool lifecycle. For use by the live server.
    
    The server manages init_pool/close_pool; this function only runs the
    orchestrator graph and pushes progress events to the queue.
    
    Args:
        deck_id: Deck ID (must already exist or topic must be provided)
        topic: Topic for new deck (creates deck if deck_id is None)
        target_slides: Number of slides to generate
        progress_queue: Optional asyncio.Queue for progress updates
        
    Returns:
        Final run report
    """
    target_slides = target_slides if target_slides is not None else get_target_slides()
    run_id = None
    generation_failed = False
    final_state = {}
    try:
        await load_intent_type_map()
        await load_slide_type_configs()
        from src.content_utils import init_content_field_map
        from src.models import SLIDE_TYPE_CONFIGS
        init_content_field_map(SLIDE_TYPE_CONFIGS)
        await load_prompt_templates()

        # Create or use existing deck
        if deck_id is None:
            if topic is None:
                raise ValueError("Either deck_id or topic must be provided")
            deck_id = await tool_call("mcp_create_deck", topic=topic, target_slides=target_slides)
            logger.info(f"Created new deck: {deck_id}")
        else:
            logger.info(f"Continuing deck: {deck_id}")
        
        # --- Lifecycle: start ---
        run_config = _build_run_config()
        run_config["target_slides"] = target_slides
        run_id = await _start_generation_run(deck_id, run_config)
        await _set_deck_status(deck_id, "generating")

        # Create initial state with DB run_id
        state = create_initial_state(deck_id, run_id=run_id)
        state["target_slides"] = target_slides
        
        # Seed used_image_ids for deck continuation
        if topic is None:
            try:
                async with get_connection() as conn:
                    rows = await conn.fetch(
                        "SELECT DISTINCT image_id::text FROM slide WHERE deck_id = $1 AND image_id IS NOT NULL",
                        UUID(deck_id),
                    )
                    state["used_image_ids"] = [r["image_id"] for r in rows]
                    logger.info(f"Loaded {len(state['used_image_ids'])} existing images for dedup")
            except Exception as e:
                logger.warning(f"Could not seed used_image_ids: {e}")
        
        # Build graph
        graph = build_orchestrator_graph()
        
        # Wrap nodes with progress hooks if queue provided
        if progress_queue:
            node_names = [
                "pick_intent", "retrieve", "draft", "validate_format",
                "validate_citations", "check_grounding", "check_novelty",
                "select_image", "commit",
            ]
            for name in node_names:
                if name in graph.nodes:
                    graph.nodes[name] = _wrap_node_with_progress(
                        graph.nodes[name], name, progress_queue
                    )
        
        # Compile and run
        compiled = graph.compile()
        
        logger.info("Starting headless generation loop...")
        final_state = await compiled.ainvoke(state)
        
        run_status = _determine_run_status(final_state)

        # Generate and return report
        report = await tool_call("mcp_get_run_report", deck_id=deck_id)
        
        # Check if fallback was triggered
        total_failures = len(final_state.get("failed_intents", [])) + len(final_state.get("abandoned_intents", []))
        fallback_triggered = total_failures > run_config.get("max_failed_intents", 3)
        
        # Add orchestrator metrics
        report["orchestrator_metrics"] = {
            "llm_calls": final_state.get("llm_calls", 0),
            "embeddings_generated": final_state.get("embeddings_generated", 0),
            "total_retries": final_state.get("total_retries", 0),
            "slides_generated": len(final_state.get("generated_slides", [])),
            "failed_intents": final_state.get("failed_intents", []),
            "abandoned_intents": final_state.get("abandoned_intents", []),
            "images_deduplicated": final_state.get("images_deduplicated", 0),
            "fallback_triggered": fallback_triggered,
            "cost": {
                "prompt_tokens": final_state.get("prompt_tokens", 0),
                "completion_tokens": final_state.get("completion_tokens", 0),
                "embedding_tokens": final_state.get("embedding_tokens", 0),
                "estimated_cost_usd": final_state.get("estimated_cost_usd", 0.0),
            },
        }
        
        _cost = report["orchestrator_metrics"]["cost"]
        logger.info(
            f"Headless generation complete. Slides: {len(final_state['generated_slides'])} | "
            f"LLM calls: {report['orchestrator_metrics']['llm_calls']} | "
            f"Tokens: {_cost['prompt_tokens']}in + {_cost['completion_tokens']}out + {_cost['embedding_tokens']}emb | "
            f"Cost: ${_cost['estimated_cost_usd']:.4f}"
        )
        
        if progress_queue:
            await progress_queue.put({"type": "complete", "deck_id": deck_id})
        
        return report
        
    except Exception as e:
        generation_failed = True
        logger.error("Generation failed with exception", exc_info=True)
        if progress_queue:
            await progress_queue.put({
                "type": "error",
                "deck_id": deck_id or "unknown",
                "error": str(e),
            })
        raise

    finally:
        status = "failed"
        if run_id:
            status = "failed" if generation_failed else _determine_run_status(final_state)
            try:
                await _complete_generation_run(run_id, final_state, status=status)
            except Exception:
                pass
        if deck_id:
            deck_status = "failed" if generation_failed else (
                "completed" if status in ("completed", "cost_limited") else "failed"
            )
            try:
                await _set_deck_status(deck_id, deck_status)
            except Exception:
                pass


async def run_generation(
    deck_id: Optional[str] = None,
    topic: Optional[str] = None,
    target_slides: int | None = None,
) -> dict:
    """
    Run the slide generation loop.
    
    Args:
        deck_id: Existing deck to continue, or None to create new
        topic: Topic for new deck (required if deck_id is None)
        target_slides: Number of slides to generate
        
    Returns:
        Final run report
    """
    # Initialize database pool, config, and MCP client
    await init_pool()
    await config.init_config()
    await init_mcp_client()

    from src.renderer import init_renderer
    await init_renderer()

    target_slides = target_slides if target_slides is not None else get_target_slides()

    # Cleanup stale generating decks from previous crashes
    await cleanup_stale_generating()

    run_id = None
    deck_id_local = deck_id
    generation_failed = False
    final_state = {}
    try:
        # Create or use existing deck
        if deck_id_local is None:
            if topic is None:
                raise ValueError("Either deck_id or topic must be provided")
            deck_id_local = await tool_call("mcp_create_deck", topic=topic, target_slides=target_slides)
            logger.info(f"Created new deck: {deck_id_local}")
        else:
            logger.info(f"Continuing deck: {deck_id_local}")
        
        # Start generation_run tracking
        run_config = _build_run_config()
        run_config["target_slides"] = target_slides
        run_id = await _start_generation_run(deck_id_local, run_config)
        await _set_deck_status(deck_id_local, "generating")

        # Create initial state with DB run_id
        state = create_initial_state(deck_id_local, run_id=run_id)
        state["target_slides"] = target_slides
        
        # Seed used_image_ids for deck continuation (--deck-id)
        if deck_id is not None and topic is None:
            async with get_connection() as conn:
                rows = await conn.fetch(
                    "SELECT DISTINCT image_id::text FROM slide WHERE deck_id = $1 AND image_id IS NOT NULL",
                    UUID(deck_id_local),
                )
                state["used_image_ids"] = [r["image_id"] for r in rows]
                logger.info(f"Loaded {len(state['used_image_ids'])} existing images for dedup")
        
        # Build and compile graph
        graph = build_orchestrator_graph()
        compiled = graph.compile()
        
        # Run generation
        logger.info("Starting generation loop...")
        final_state = await compiled.ainvoke(state)
        
        run_status = _determine_run_status(final_state)

        # Generate and return report
        report = await tool_call("mcp_get_run_report", deck_id=deck_id_local)
        
        # Check if fallback was triggered
        total_failures = len(final_state.get("failed_intents", [])) + len(final_state.get("abandoned_intents", []))
        fallback_triggered = total_failures > run_config.get("max_failed_intents", 3)
        
        # Add orchestrator metrics
        report["orchestrator_metrics"] = {
            "llm_calls": final_state.get("llm_calls", 0),
            "embeddings_generated": final_state.get("embeddings_generated", 0),
            "total_retries": final_state.get("total_retries", 0),
            "slides_generated": len(final_state.get("generated_slides", [])),
            "failed_intents": final_state.get("failed_intents", []),
            "abandoned_intents": final_state.get("abandoned_intents", []),
            "images_deduplicated": final_state.get("images_deduplicated", 0),
            "fallback_triggered": fallback_triggered,
            "cost": {
                "prompt_tokens": final_state.get("prompt_tokens", 0),
                "completion_tokens": final_state.get("completion_tokens", 0),
                "embedding_tokens": final_state.get("embedding_tokens", 0),
                "estimated_cost_usd": final_state.get("estimated_cost_usd", 0.0),
            },
        }
        
        _cost = report["orchestrator_metrics"]["cost"]
        logger.info(
            f"Generation complete. Slides: {len(final_state['generated_slides'])} | "
            f"Retries: {final_state['total_retries']} | "
            f"LLM calls: {report['orchestrator_metrics']['llm_calls']} | "
            f"Tokens: {_cost['prompt_tokens']}in + {_cost['completion_tokens']}out + {_cost['embedding_tokens']}emb | "
            f"Cost: ${_cost['estimated_cost_usd']:.4f}"
        )
        
        return report

    except Exception as e:
        generation_failed = True
        raise

    finally:
        status = "failed"
        if run_id:
            status = "failed" if generation_failed else _determine_run_status(final_state)
            try:
                await _complete_generation_run(run_id, final_state, status=status)
            except Exception:
                pass
        if deck_id_local:
            deck_status = "failed" if generation_failed else (
                "completed" if status in ("completed", "cost_limited") else "failed"
            )
            try:
                await _set_deck_status(deck_id_local, deck_status)
            except Exception:
                pass
        await close_mcp_client()
        await close_pool()


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    """CLI entry point for orchestrator."""
    parser = argparse.ArgumentParser(
        description="Slide Generation Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate slides for new deck
  python -m src.orchestrator --topic "Postgres as AI Control Plane"
  
  # Continue generation for existing deck
  python -m src.orchestrator --deck-id <uuid>
        """
    )
    
    parser.add_argument(
        "--deck-id",
        type=str,
        help="UUID of existing deck to continue"
    )
    parser.add_argument(
        "--topic",
        type=str,
        help="Topic for new deck"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if not args.deck_id and not args.topic:
        parser.error("Either --deck-id or --topic must be provided")
    
    # Run orchestrator
    report = asyncio.run(run_generation(
        deck_id=args.deck_id,
        topic=args.topic,
    ))
    
    # Print summary
    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)
    print(f"\nDeck ID: {report.get('deck_id')}")
    print(f"Generated at: {report.get('generated_at')}")
    
    summary = report.get("summary", {})
    print(f"\nSlides: {summary.get('total_slides', 0)} / {summary.get('target_slides', get_target_slides())}")
    print(f"Coverage: {summary.get('coverage_pct', 0):.1f}%")
    
    metrics = report.get("orchestrator_metrics", {})
    print(f"\nLLM Calls: {metrics.get('llm_calls', 0)}")
    print(f"Embeddings: {metrics.get('embeddings_generated', 0)}")
    print(f"Retries: {metrics.get('total_retries', 0)}")
    
    if metrics.get("failed_intents"):
        print(f"\nFailed intents: {metrics['failed_intents']}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
