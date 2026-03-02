-- Migration 016: Make gates a static image slide
--
-- The "Control Gates & Validation" slide renders the pre-built
-- gate-chain-diagram.png as the sole visual. Instead of forcing it through
-- the LLM generation pipeline (which fails on retrieval/grounding for an
-- image-only slide), we make it a static slide inserted by the renderer
-- like section dividers -- it appears at its position in the intent order
-- when surrounding slides exist, costing zero LLM tokens.
--
-- This migration:
--   A. Drops the image_only column (no longer needed)
--   B. Marks gates as non-generatable and reverts slide_type to flow
--   C. Adds a static_slide row for gates with image reference

-- ─────────────────────────────────────────────────────────────────────────────
-- A. Drop image_only column (was added in a prior version of this migration)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE intent_type_map
    DROP COLUMN IF EXISTS image_only;

-- ─────────────────────────────────────────────────────────────────────────────
-- B. Mark gates as non-generatable; revert to original slide_type
-- ─────────────────────────────────────────────────────────────────────────────

UPDATE intent_type_map
SET is_generatable  = false,
    slide_type      = 'flow',
    require_image   = false,
    requirements    = 'Gate chain validation pipeline: G0 ingestion, G1 retrieval quality, G2 citation, G2.5 grounding, G3 format, G4 novelty, G5 commit.'
WHERE intent = 'gates';

-- ─────────────────────────────────────────────────────────────────────────────
-- C. Add image columns to static_slide (for image-bearing static slides)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE static_slide
    ADD COLUMN IF NOT EXISTS image_path TEXT,
    ADD COLUMN IF NOT EXISTS image_alt  TEXT;

-- ─────────────────────────────────────────────────────────────────────────────
-- D. Insert static slide for gates (image-only, no LLM content)
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO static_slide (intent, title, slide_type, bullets, content_data, speaker_notes, image_path, image_alt)
VALUES (
    'gates',
    'Control Gates & Validation',
    'diagram',
    '[]'::jsonb,
    '{}'::jsonb,
    'Every slide passes through a chain of PL/pgSQL validation gates before it can be committed to the deck. G0 validates ingestion quality. G1 checks retrieval relevance. G2 validates citations exist and are properly sourced. G2.5 verifies semantic grounding against the cited chunks. G3 enforces structural format constraints. G4 ensures novelty so slides do not repeat. G5 is the final commit gate. All gates are SQL functions -- deterministic, auditable, and zero LLM cost.',
    'gate-chain-diagram.png',
    'Gate chain validation pipeline: G0 through G5 sequential PL/pgSQL gates'
)
ON CONFLICT (intent) DO UPDATE
SET title         = EXCLUDED.title,
    slide_type    = EXCLUDED.slide_type,
    bullets       = EXCLUDED.bullets,
    content_data  = EXCLUDED.content_data,
    speaker_notes = EXCLUDED.speaker_notes,
    image_path    = EXCLUDED.image_path,
    image_alt     = EXCLUDED.image_alt;
