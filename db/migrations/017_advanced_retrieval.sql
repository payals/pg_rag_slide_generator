-- Migration 017: Add "Beyond Vector Search" (advanced-retrieval) intent
--
-- Adds a new generatable slide covering two-stage retrieval:
--   Stage 1: RRF hybrid search inside Postgres
--   Stage 2: Cross-encoder reranking in Python
--
-- Inserted after rag-in-postgres (sort_order 9) at sort_order 10.
-- All downstream intents bump by 1.

-- ─────────────────────────────────────────────────────────────────────────────
-- A. Extend the slide_intent enum
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TYPE slide_intent ADD VALUE IF NOT EXISTS 'advanced-retrieval' AFTER 'rag-in-postgres';

-- ─────────────────────────────────────────────────────────────────────────────
-- B. Bump sort_orders for all intents currently at 10+
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE intent_type_map
SET sort_order = sort_order + 1
WHERE sort_order >= 10
  AND intent NOT IN ('title', 'thanks');

-- ─────────────────────────────────────────────────────────────────────────────
-- C. Insert the new intent
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO intent_type_map (
    intent, slide_type, require_image, min_bullets, max_bullets, max_bullet_words,
    sort_order, suggested_title, requirements, is_generatable, related_intents
)
VALUES (
    'advanced-retrieval',
    'split',
    false,
    0, 0, 15,
    10,
    'Beyond Vector Search',
    'Split layout comparing two retrieval stages. Left: Reciprocal Rank Fusion (RRF) combining semantic (pgvector cosine) and lexical (tsvector ts_rank_cd) search inside Postgres with formula 1/(k+rank). Right: cross-encoder reranking in Python using ms-marco-MiniLM-L6-v2 for precision re-scoring of top-K candidates.',
    true,
    ARRAY['rag-in-postgres', 'what-is-rag']
)
ON CONFLICT (intent) DO UPDATE SET
    slide_type      = EXCLUDED.slide_type,
    sort_order      = EXCLUDED.sort_order,
    suggested_title = EXCLUDED.suggested_title,
    requirements    = EXCLUDED.requirements,
    is_generatable  = EXCLUDED.is_generatable,
    related_intents = EXCLUDED.related_intents;
