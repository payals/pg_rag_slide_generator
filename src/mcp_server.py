"""
MCP Server for Postgres-First AI Slide Generator.

Provides typed tool interfaces that wrap Postgres SQL functions,
creating a safety boundary where the LLM can retrieve knowledge
and manage deck state without raw database access.

Tools:
- Knowledge: mcp_search_chunks, mcp_get_chunk
- Deck: mcp_create_deck, mcp_get_deck_state, mcp_pick_next_intent
- Gate: mcp_check_retrieval_quality, mcp_validate_slide_structure, mcp_validate_citations, mcp_check_novelty, mcp_check_grounding
- Commit: mcp_commit_slide, mcp_get_run_report
- Image: mcp_search_images, mcp_get_image, mcp_validate_image

Usage:
    # Run with FastMCP CLI
    fastmcp run src/mcp_server.py
    
    # Or programmatically
    from src.mcp_server import mcp
    mcp.run()
"""

import json
import logging
import os
from typing import Optional
from uuid import UUID

import asyncpg
from dotenv import load_dotenv
from fastmcp import FastMCP
from openai import AsyncOpenAI
import httpx
from sentence_transformers import CrossEncoder

from src.db import get_connection, close_pool, init_pool
from src.models import (
    ChunkDetail,
    ChunkResult,
    CitationValidationResult,
    CommitResult,
    DeckState,
    GroundingResult,
    ImageSearchResult,
    NoveltyResult,
    RunReport,
    SearchFilters,
    SlideSpec,
    StyleContract,
    ValidationResult,
    extract_slide_text,
)

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Secrets/infra from env (not in config table)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
OPENAI_USER = os.getenv("OPENAI_USER")
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() != "false"

# All operational config loaded from Postgres via src.config (after init_config)
from src import config

# Import get_target_slides from renderer (DB-backed)
from src.renderer import get_target_slides

# Initialize FastMCP server
mcp = FastMCP(
    "slidegen",
    instructions="Postgres-First AI Slide Generator - MCP Server for RAG and deck management. Use the tools to search knowledge, create decks, validate slides, and commit content."
)

# OpenAI client singleton
_openai_client: Optional[AsyncOpenAI] = None

# Reranker singleton
_reranker: Optional[CrossEncoder] = None


# =============================================================================
# SHARED HELPERS
# =============================================================================


def get_reranker() -> CrossEncoder:
    """Get or create the CrossEncoder reranker model (lazy-loaded singleton)."""
    global _reranker
    
    if _reranker is None:
        model_name = config.get("reranker_model", "cross-encoder/ms-marco-MiniLM-L6-v2")
        logger.info(f"Loading reranker model: {model_name}")
        _reranker = CrossEncoder(model_name)
        logger.info("Reranker model loaded")
    
    return _reranker


def rerank_chunks(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    """
    Rerank chunks using cross-encoder model for improved precision.
    
    Takes initial candidates from hybrid search and reranks them using
    a cross-encoder that scores query-document pairs directly.
    """
    if not chunks:
        return chunks
    
    try:
        reranker = get_reranker()
        pairs = [(query, chunk["content"]) for chunk in chunks]
        scores = reranker.predict(pairs)
        
        for chunk, score in zip(chunks, scores):
            chunk["rerank_score"] = float(score)
        
        reranked = sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)[:top_k]
        logger.info(f"Reranked {len(chunks)} chunks -> top {len(reranked)}")
        return reranked
        
    except Exception as e:
        logger.warning(f"Reranking failed, returning original results: {e}")
        return chunks[:top_k]


async def get_openai_client() -> AsyncOpenAI:
    """Get or create the async OpenAI client."""
    global _openai_client
    
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        
        http_client = None if SSL_VERIFY else httpx.AsyncClient(verify=False)
        client_kwargs = {"api_key": OPENAI_API_KEY}
        if OPENAI_API_BASE:
            client_kwargs["base_url"] = OPENAI_API_BASE
        if http_client:
            client_kwargs["http_client"] = http_client
        
        _openai_client = AsyncOpenAI(**client_kwargs)
    
    return _openai_client


async def get_embedding(text: str) -> list[float]:
    """Get embedding for text using OpenAI API."""
    client = await get_openai_client()
    
    kwargs = {
        "model": config.get("openai_embedding_model", "text-embedding-3-small"),
        "input": text
    }
    if OPENAI_USER:
        kwargs["user"] = OPENAI_USER
    
    response = await client.embeddings.create(**kwargs)
    return response.data[0].embedding


async def _get_image(image_id: str) -> dict:
    """
    Get full image metadata by ID. Private helper used by mcp_get_image
    and mcp_validate_image to avoid tool-calls-tool.
    """
    logger.info(f"_get_image: image_id={image_id}")
    
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT 
                ia.image_id, ia.doc_id, ia.storage_path, ia.caption, ia.alt_text,
                ia.use_cases, ia.license, ia.attribution, ia.style,
                ia.width, ia.height, ia.created_at
            FROM image_asset ia
            WHERE ia.image_id = $1
            """,
            UUID(image_id),
        )
        
        if not row:
            raise ValueError(f"Image not found: {image_id}")
        
        return {
            "image_id": str(row["image_id"]),
            "doc_id": str(row["doc_id"]),
            "storage_path": row["storage_path"],
            "caption": row["caption"],
            "alt_text": row["alt_text"],
            "use_cases": list(row["use_cases"]) if row["use_cases"] else [],
            "license": row["license"],
            "attribution": row["attribution"],
            "style": row["style"] if row["style"] else None,
            "width": row["width"],
            "height": row["height"],
        }


# =============================================================================
# MCP TOOLS
# =============================================================================


def _register(fn):
    """Register fn as an MCP tool while preserving it as a regular callable."""
    mcp.tool()(fn)
    return fn


@_register
async def mcp_search_chunks(
    query: str,
    doc_type: Optional[str] = None,
    trust_level: Optional[str] = None,
    tags: Optional[list[str]] = None,
    top_k: int = None,
    semantic_weight: float = None,
    lexical_weight: float = None,
) -> list[dict]:
    """
    Search knowledge base with hybrid semantic+lexical retrieval.
    
    Combines vector similarity (semantic) with full-text search (lexical)
    using Reciprocal Rank Fusion (RRF) for ranking.
    
    Args:
        query: Search query text
        doc_type: Filter by document type (note, article, concept, blog, external)
        trust_level: Filter by trust level (low, medium, high)
        tags: Filter by tags (any match)
        top_k: Number of results to return
        semantic_weight: Weight for semantic search
        lexical_weight: Weight for lexical search
    
    Returns:
        List of matching chunks with scores
    """
    if top_k is None:
        top_k = config.get("default_top_k", 10)
    if semantic_weight is None:
        semantic_weight = config.get("semantic_weight", 0.7)
    if lexical_weight is None:
        lexical_weight = config.get("lexical_weight", 0.3)
    rerank_enabled = config.get("rerank_enabled", True)
    logger.info(f"mcp_search_chunks: query='{query[:50]}...', top_k={top_k}, rerank={rerank_enabled}")
    
    filters = {}
    if doc_type:
        filters["doc_type"] = doc_type
    if trust_level:
        filters["trust_level"] = trust_level
    if tags:
        filters["tags"] = tags
    
    embedding = await get_embedding(query)
    fetch_k = config.get("rerank_top_k", 50) if rerank_enabled else top_k
    
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM fn_hybrid_search($1, $2, $3, $4, $5, $6)
            """,
            str(embedding),
            query,
            json.dumps(filters),
            fetch_k,
            semantic_weight,
            lexical_weight
        )
        
        results = []
        for row in rows:
            results.append({
                "chunk_id": str(row["chunk_id"]),
                "doc_id": str(row["doc_id"]),
                "content": row["content"],
                "doc_title": row["doc_title"],
                "trust_level": row["trust_level"],
                "semantic_score": float(row["semantic_score"]),
                "lexical_score": float(row["lexical_score"]),
                "combined_score": float(row["combined_score"]),
                "semantic_rank": row["semantic_rank"],
                "lexical_rank": row["lexical_rank"],
            })
        
        if rerank_enabled and results:
            results = rerank_chunks(query, results, top_k)
            logger.info(f"mcp_search_chunks: reranked to {len(results)} results")
        else:
            logger.info(f"mcp_search_chunks: returned {len(results)} results (no rerank)")
        
        return results


@_register
async def mcp_get_chunk(chunk_id: str) -> dict:
    """
    Retrieve a single chunk by ID with full metadata.
    
    Args:
        chunk_id: UUID of the chunk to retrieve
    
    Returns:
        Chunk details including content, metadata, and source document info
    """
    logger.info(f"mcp_get_chunk: chunk_id={chunk_id}")
    
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT 
                c.chunk_id, c.doc_id, c.content, c.content_hash,
                c.section_header, c.token_count,
                d.title as doc_title, d.doc_type, d.trust_level, d.tags
            FROM chunk c
            JOIN doc d ON c.doc_id = d.doc_id
            WHERE c.chunk_id = $1
            """,
            UUID(chunk_id)
        )
        
        if not row:
            raise ValueError(f"Chunk not found: {chunk_id}")
        
        return {
            "chunk_id": str(row["chunk_id"]),
            "doc_id": str(row["doc_id"]),
            "content": row["content"],
            "content_hash": row["content_hash"],
            "section_header": row["section_header"],
            "token_count": row["token_count"],
            "doc_title": row["doc_title"],
            "doc_type": row["doc_type"],
            "trust_level": row["trust_level"],
            "tags": row["tags"] or [],
        }


@_register
async def mcp_create_deck(
    topic: str,
    target_slides: int | None = None,
    description: Optional[str] = None,
    tone: Optional[str] = None,
    audience: Optional[str] = None,
    bullet_style: Optional[str] = None,
) -> str:
    """
    Create a new deck for slide generation.
    
    Args:
        topic: Main topic/title of the presentation
        target_slides: Number of slides to generate
        description: Optional description of the presentation
        tone: Presentation tone (default: "technical")
        audience: Target audience (default: "developers")
        bullet_style: Bullet point style (default: "concise")
    
    Returns:
        UUID of the created deck
    """
    target_slides = target_slides if target_slides is not None else get_target_slides()
    logger.info(f"mcp_create_deck: topic='{topic}', target_slides={target_slides}")
    
    style_contract = {}
    if tone:
        style_contract["tone"] = tone
    if audience:
        style_contract["audience"] = audience
    if bullet_style:
        style_contract["bullet_style"] = bullet_style
    
    async with get_connection() as conn:
        deck_id = await conn.fetchval(
            """
            SELECT fn_create_deck($1, $2, $3, $4)
            """,
            topic,
            target_slides,
            json.dumps(style_contract),
            description
        )
        
        logger.info(f"mcp_create_deck: created deck_id={deck_id}")
        return str(deck_id)


@_register
async def mcp_get_deck_state(deck_id: str) -> dict:
    """
    Get current state of a deck including coverage and health metrics.
    
    Args:
        deck_id: UUID of the deck
    
    Returns:
        Deck state with coverage info, health metrics, and slide list
    """
    logger.info(f"mcp_get_deck_state: deck_id={deck_id}")
    
    async with get_connection() as conn:
        result = await conn.fetchval(
            """
            SELECT fn_get_deck_state($1)
            """,
            UUID(deck_id)
        )
        
        if not result:
            raise ValueError(f"Deck not found: {deck_id}")
        
        return json.loads(result) if isinstance(result, str) else result


@_register
async def mcp_pick_next_intent(
    deck_id: str,
    exclude: Optional[list[str]] = None,
) -> Optional[str]:
    """
    Deterministically select the next missing intent for slide generation.
    
    Follows a canonical order to ensure consistent deck structure.
    Skips intents in the exclude list (e.g. abandoned intents).
    
    Args:
        deck_id: UUID of the deck
        exclude: Optional list of intents to skip
    
    Returns:
        Next intent to generate, or None if all intents are covered
    """
    logger.info(f"mcp_pick_next_intent: deck_id={deck_id}, exclude={exclude or []}")
    
    async with get_connection() as conn:
        intent = await conn.fetchval(
            """
            SELECT fn_pick_next_intent($1, $2::slide_intent[])
            """,
            UUID(deck_id),
            exclude or [],
        )
        
        logger.info(f"mcp_pick_next_intent: next_intent={intent}")
        return intent


@_register
async def mcp_check_retrieval_quality(
    search_results: list[dict],
    min_chunks: int = None,
    min_score: float = None,
) -> dict:
    """
    Evaluate retrieval quality (Gate G1).
    
    Checks that hybrid search returned enough relevant chunks
    with sufficient combined score. Thresholds come from the
    Postgres config table.
    
    Args:
        search_results: List of chunk dicts from mcp_search_chunks
        min_chunks: Minimum number of chunks required
        min_score: Minimum combined_score for the top result
    
    Returns:
        Result with is_valid, chunk_count, top_score, and errors
    """
    if min_chunks is None:
        min_chunks = config.get("g1_min_chunks", 3)
    if min_score is None:
        min_score = config.get("g1_min_score", 0.3)
    logger.info(f"mcp_check_retrieval_quality: {len(search_results)} chunks, min_chunks={min_chunks}, min_score={min_score}")

    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM fn_check_retrieval_quality($1, $2, $3)",
            json.dumps(search_results),
            min_chunks,
            min_score,
        )

        errors = row["errors"]
        if isinstance(errors, str):
            errors = json.loads(errors)

        result = {
            "is_valid": row["is_valid"],
            "chunk_count": row["chunk_count"],
            "top_score": float(row["top_score"]) if row["top_score"] else 0.0,
            "errors": errors if errors else [],
        }
        logger.info(f"mcp_check_retrieval_quality: is_valid={result['is_valid']}, count={result['chunk_count']}, top={result['top_score']:.3f}")
        return result


@_register
async def mcp_validate_slide_structure(slide_spec: dict) -> dict:
    """
    Validate slide format and constraints (Gate G3).
    
    Checks required fields, bullet count, bullet length, and speaker notes.
    Validation defaults (min/max bullets, max words) are owned by Postgres
    via the intent_type_map table.
    
    Args:
        slide_spec: Slide specification to validate
    
    Returns:
        Validation result with is_valid and errors list
    """
    logger.info(f"mcp_validate_slide_structure: intent={slide_spec.get('intent')}")
    
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM fn_validate_slide_structure($1)",
            json.dumps(slide_spec),
        )
        
        errors = row["errors"]
        if isinstance(errors, str):
            errors = json.loads(errors)
        
        result = {
            "is_valid": row["is_valid"],
            "errors": errors if errors else [],
        }
        logger.info(f"mcp_validate_slide_structure: is_valid={result['is_valid']}")
        return result


@_register
async def mcp_validate_citations(
    slide_spec: dict,
    min_citations: int = 1,
) -> dict:
    """
    Validate slide citations reference real chunks (Gate G2).
    
    Args:
        slide_spec: Slide specification to validate
        min_citations: Minimum number of citations required (default: 1)
    
    Returns:
        Validation result with is_valid, citation_count, and errors
    """
    logger.info(f"mcp_validate_citations: intent={slide_spec.get('intent')}")
    
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM fn_validate_citations($1, $2)
            """,
            json.dumps(slide_spec),
            min_citations
        )
        
        errors = row["errors"]
        if isinstance(errors, str):
            errors = json.loads(errors)
        
        result = {
            "is_valid": row["is_valid"],
            "citation_count": row["citation_count"],
            "errors": errors if errors else [],
        }
        logger.info(f"mcp_validate_citations: is_valid={result['is_valid']}, count={result['citation_count']}")
        return result


@_register
async def mcp_check_novelty(
    deck_id: str,
    candidate_text: str,
    threshold: float = None,
) -> dict:
    """
    Check if candidate content is novel vs existing slides (Gate G4).
    
    Prevents duplicate or overly similar slides in the deck.
    
    Args:
        deck_id: UUID of the deck
        candidate_text: Text to check for novelty (title + bullets + notes)
        threshold: Similarity threshold (higher = stricter)
    
    Returns:
        Novelty result with is_novel, max_similarity, and most similar slide info
    """
    if threshold is None:
        threshold = config.get("novelty_threshold", 0.85)
    logger.info(f"mcp_check_novelty: deck_id={deck_id}, threshold={threshold}")
    
    embedding = await get_embedding(candidate_text)
    
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM fn_check_novelty($1, $2, $3)
            """,
            UUID(deck_id),
            str(embedding),
            threshold
        )
        
        result = {
            "is_novel": row["is_novel"],
            "max_similarity": float(row["max_similarity"]) if row["max_similarity"] else 0.0,
            "most_similar_slide_no": row["most_similar_slide_no"],
            "most_similar_intent": row["most_similar_intent"],
        }
        logger.info(f"mcp_check_novelty: is_novel={result['is_novel']}, max_sim={result['max_similarity']:.3f}")
        return result


@_register
async def mcp_check_grounding(
    slide_spec: dict,
    threshold: float = None,
    run_id: Optional[str] = None,
) -> dict:
    """
    Verify each bullet is semantically grounded in cited chunks (Gate G2.5).
    
    Critical for RAG integrity - ensures slides come from sources, not hallucination.
    
    Args:
        slide_spec: Slide specification with bullets and citations
        threshold: Minimum similarity for grounding
        run_id: Optional run ID for logging
    
    Returns:
        Grounding result with is_grounded, ungrounded bullets, and details
    """
    if threshold is None:
        threshold = config.get("grounding_threshold", 0.3)
    logger.info(f"mcp_check_grounding: intent={slide_spec.get('intent')}, threshold={threshold}")
    
    segments = extract_slide_text(slide_spec)
    if not segments:
        return {
            "is_grounded": False,
            "ungrounded_bullets": [],
            "min_similarity": 0.0,
            "grounding_details": [{"error": "No text segments to ground"}],
        }
    
    bullet_embeddings = []
    for seg in segments:
        emb = await get_embedding(seg)
        bullet_embeddings.append(emb)
    
    async with get_connection() as conn:
        embeddings_array = "ARRAY[" + ",".join([f"'{emb}'::vector(1536)" for emb in bullet_embeddings]) + "]"
        
        row = await conn.fetchrow(
            f"""
            SELECT * FROM fn_check_grounding($1, {embeddings_array}, $2, $3)
            """,
            json.dumps(slide_spec),
            threshold,
            UUID(run_id) if run_id else None
        )
        
        grounding_details = row["grounding_details"]
        if isinstance(grounding_details, str):
            grounding_details = json.loads(grounding_details)
        
        result = {
            "is_grounded": row["is_grounded"],
            "ungrounded_bullets": list(row["ungrounded_bullets"]) if row["ungrounded_bullets"] else [],
            "min_similarity": float(row["min_similarity"]) if row["min_similarity"] else 0.0,
            "grounding_details": grounding_details if grounding_details else [],
        }
        logger.info(f"mcp_check_grounding: is_grounded={result['is_grounded']}, min_sim={result['min_similarity']:.3f}")
        return result


@_register
async def mcp_search_images(
    query: str,
    filters: Optional[dict] = None,
    top_k: int = 5,
) -> list[dict]:
    """
    Search images by semantic similarity to query.
    
    Finds relevant images (diagrams, screenshots, charts) for slide content.
    
    Args:
        query: Search query text
        filters: Optional filters (style, use_cases)
        top_k: Number of results (default: 5)
    
    Returns:
        List of matching images ranked by similarity
    """
    logger.info(f"mcp_search_images: query='{query[:50]}...', top_k={top_k}")
    
    embedding = await get_embedding(query)
    filter_json = json.dumps(filters or {})
    
    async with get_connection() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM fn_search_images($1, $2, $3)
            """,
            str(embedding),
            filter_json,
            top_k,
        )
        
        results = []
        for row in rows:
            results.append({
                "image_id": str(row["image_id"]),
                "storage_path": row["storage_path"],
                "caption": row["caption"],
                "alt_text": row["alt_text"],
                "use_cases": list(row["use_cases"]) if row["use_cases"] else [],
                "style": row["style"] if row["style"] else None,
                "similarity": float(row["similarity"]),
            })
        
        logger.info(f"mcp_search_images: returned {len(results)} results")
        return results


@_register
async def mcp_get_image(image_id: str) -> dict:
    """
    Get full image metadata by ID.
    
    Args:
        image_id: UUID of the image asset
    
    Returns:
        Image metadata including storage_path, caption, alt_text, license, attribution
    """
    return await _get_image(image_id)


@_register
async def mcp_validate_image(image_id: str) -> dict:
    """
    G5 gate: Validate image eligibility for slide inclusion.
    
    Checks license, attribution, and file existence.
    
    Args:
        image_id: UUID of the image asset
    
    Returns:
        Validation result with is_valid and errors list
    """
    logger.info(f"mcp_validate_image: image_id={image_id}")
    
    errors = []
    
    try:
        image = await _get_image(image_id)
    except ValueError:
        return {"is_valid": False, "errors": [f"Image not found: {image_id}"]}
    
    if not image.get("license") or not image["license"].strip():
        errors.append("Missing license")
    if not image.get("attribution") or not image["attribution"].strip():
        errors.append("Missing attribution")
    
    from pathlib import Path
    image_content_dir = Path(os.getenv("IMAGE_CONTENT_DIR", "content/images"))
    file_path = image_content_dir / image["storage_path"]
    if not file_path.exists():
        errors.append(f"File not found: {image['storage_path']}")
    
    result = {
        "is_valid": len(errors) == 0,
        "errors": errors,
    }
    logger.info(f"mcp_validate_image: is_valid={result['is_valid']}")
    return result


@_register
async def mcp_log_gate(
    run_id: str,
    deck_id: str,
    slide_no: int,
    gate_name: str,
    decision: str,
    score: Optional[float] = None,
    threshold: Optional[float] = None,
    reason: Optional[str] = None,
    payload: Optional[dict] = None,
) -> dict:
    """
    Log a gate check result to gate_log via fn_log_gate.

    Args:
        run_id: UUID of the generation run
        deck_id: UUID of the deck
        slide_no: Slide number (1-based)
        gate_name: Gate identifier (e.g. G3_format)
        decision: "pass" or "fail"
        score: Optional numeric score
        threshold: Optional threshold used for the check
        reason: Optional failure reason text
        payload: Optional JSONB details

    Returns:
        Dict with log_id of the created gate_log entry
    """
    async with get_connection() as conn:
        log_id = await conn.fetchval(
            "SELECT fn_log_gate($1::uuid, $2::uuid, $3::int, $4::text, "
            "$5::gate_decision, $6::float, $7::float, $8::text, $9::jsonb)",
            UUID(run_id),
            UUID(deck_id),
            slide_no,
            gate_name,
            decision,
            score,
            threshold,
            reason,
            json.dumps(payload) if payload else "{}",
        )
        return {"log_id": str(log_id)}


@_register
async def mcp_commit_slide(
    deck_id: str,
    slide_no: int,
    slide_spec: dict,
    run_id: Optional[str] = None,
    novelty_passed: Optional[bool] = None,
    novelty_score: Optional[float] = None,
    grounding_passed: Optional[bool] = None,
    grounding_score: Optional[float] = None,
    image_id: Optional[str] = None,
    draft_retries: int = 0,
) -> dict:
    """
    Atomically commit a slide with validation (Gates G2, G3, G5).
    
    Validates citations and structure, logs gate decisions, and inserts/updates
    the slide. Novelty (G4) and grounding (G2.5) should be validated by the
    orchestrator BEFORE calling this function.
    
    Args:
        deck_id: UUID of the deck
        slide_no: Slide number (1-based)
        slide_spec: Slide specification to commit
        run_id: Optional run ID for gate logging
        novelty_passed: Result of novelty check (G4)
        novelty_score: Similarity score from novelty check
        grounding_passed: Result of grounding check (G2.5)
        grounding_score: Min similarity from grounding check
        image_id: Optional image asset ID for the slide
    
    Returns:
        Commit result with success, slide_id, and any errors
    """
    logger.info(f"mcp_commit_slide: deck_id={deck_id}, slide_no={slide_no}, intent={slide_spec.get('intent')}")
    
    async with get_connection() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM fn_commit_slide($1::uuid, $2::int, $3::jsonb, $4::uuid, $5::boolean, $6::float, $7::boolean, $8::float, $9::uuid, $10::int)
            """,
            UUID(deck_id),
            slide_no,
            json.dumps(slide_spec),
            UUID(run_id) if run_id else None,
            novelty_passed,
            novelty_score,
            grounding_passed,
            grounding_score,
            UUID(image_id) if image_id else None,
            draft_retries,
        )
        
        errors = row["errors"]
        if isinstance(errors, str):
            errors = json.loads(errors)
        
        result = {
            "success": row["success"],
            "slide_id": str(row["slide_id"]) if row["slide_id"] else None,
            "errors": errors if errors else [],
        }
        logger.info(f"mcp_commit_slide: success={result['success']}, slide_id={result['slide_id']}")
        return result


@_register
async def mcp_get_run_report(deck_id: str) -> dict:
    """
    Generate comprehensive report for a deck generation run.
    
    Includes summary metrics, coverage status, gate statistics,
    failure reasons, and slide details.
    
    Args:
        deck_id: UUID of the deck
    
    Returns:
        Full run report with all metrics and details
    """
    logger.info(f"mcp_get_run_report: deck_id={deck_id}")
    
    async with get_connection() as conn:
        result = await conn.fetchval(
            """
            SELECT fn_get_run_report($1)
            """,
            UUID(deck_id)
        )
        
        if not result:
            raise ValueError(f"Deck not found: {deck_id}")
        
        report = json.loads(result) if isinstance(result, str) else result
        logger.info(f"mcp_get_run_report: generated report for deck {deck_id}")
        return report


# =============================================================================
# SERVER LIFECYCLE
# =============================================================================


async def initialize_server():
    """Initialize resources (call before using tools)."""
    logger.info("MCP Server initializing...")
    await init_pool()
    logger.info("Database pool initialized")


async def shutdown_server():
    """Cleanup resources on shutdown."""
    logger.info("MCP Server shutting down...")
    await close_pool()
    logger.info("Database pool closed")


# =============================================================================
# MAIN
# =============================================================================


if __name__ == "__main__":
    mcp.run()
