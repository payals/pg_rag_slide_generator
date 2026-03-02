-- =============================================================================
-- Migration 013: Config table, gate-name normalization, SQL defaults
-- =============================================================================
-- Move operational config from .env into a Postgres config table.
-- Normalize all gate_log.gate_name values to lowercase.
-- Update fn_commit_slide gate name strings to match.
-- Fix fn_check_grounding default threshold.
-- =============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- A. Create config table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    value_type  TEXT NOT NULL DEFAULT 'string',
    category    TEXT NOT NULL,
    description TEXT
);

-- Populate with current operational values
INSERT INTO config (key, value, value_type, category, description) VALUES
    -- Retrieval
    ('default_top_k',              '10',    'int',    'retrieval', 'Number of chunks to retrieve'),
    ('semantic_weight',            '0.7',   'float',  'retrieval', 'Weight for semantic search in hybrid RRF'),
    ('lexical_weight',             '0.3',   'float',  'retrieval', 'Weight for lexical search in hybrid RRF'),
    -- Gate thresholds
    ('novelty_threshold',          '0.85',  'float',  'gates',     'Cosine similarity ceiling for novelty gate'),
    ('grounding_threshold',        '0.3',   'float',  'gates',     'Min similarity for bullet grounding'),
    ('grounding_threshold_diagram','0.2',   'float',  'gates',     'Min similarity for diagram grounding'),
    -- Generation limits
    ('max_retries_per_slide',      '5',     'int',    'generation','Max retries before abandoning a slide'),
    ('max_total_retries',          '100',   'int',    'generation','Global retry budget'),
    ('max_llm_calls',              '200',   'int',    'generation','Hard cap on LLM API calls'),
    ('max_failed_intents',         '3',     'int',    'generation','Consecutive failed intents before stopping'),
    -- Cost limits
    ('cost_limit_usd',             '10.00', 'float',  'cost',      'USD spend ceiling per run'),
    ('llm_input_cost_per_1k',      '0.03',  'float',  'cost',      'Input token cost per 1K tokens'),
    ('llm_output_cost_per_1k',     '0.06',  'float',  'cost',      'Output token cost per 1K tokens'),
    ('embedding_cost_per_1k',      '0.00002','float', 'cost',      'Embedding cost per 1K tokens'),
    -- Chunking
    ('chunk_size_tokens',          '700',   'int',    'chunking',  'Target chunk size in tokens'),
    ('chunk_overlap_tokens',       '100',   'int',    'chunking',  'Overlap between adjacent chunks'),
    ('min_chunk_size_tokens',      '50',    'int',    'chunking',  'Drop chunks smaller than this'),
    -- Reranking
    ('rerank_enabled',             'true',  'bool',   'reranking', 'Enable cross-encoder reranking'),
    ('reranker_model',             'cross-encoder/ms-marco-MiniLM-L6-v2', 'string', 'reranking', 'HuggingFace reranker model ID'),
    ('rerank_top_k',               '50',    'int',    'reranking', 'Candidates to fetch before reranking'),
    -- LLM
    ('openai_model',               'gpt-5', 'string', 'llm',       'OpenAI model name'),
    ('openai_embedding_model',     'text-embedding-3-small', 'string', 'llm', 'Embedding model name'),
    ('llm_temperature',            '0.7',   'float',  'llm',       'Sampling temperature'),
    ('llm_max_tokens',             '2000',  'int',    'llm',       'Max tokens in LLM response'),
    -- Images
    ('image_selection_enabled',    'true',  'bool',   'images',    'Enable image selection for slides'),
    ('image_min_score',            '0.5',   'float',  'images',    'Min similarity to select an image'),
    ('image_intent_min_score',     '0.35',  'float',  'images',    'Min score for intent-based image match'),
    ('image_style_preference',     'diagram,decorative', 'csv', 'images', 'Preferred image styles')
ON CONFLICT (key) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- B. Normalize gate names to lowercase
-- ─────────────────────────────────────────────────────────────────────────────

-- Drop old mixed-case CHECK constraint BEFORE updating rows
ALTER TABLE gate_log DROP CONSTRAINT IF EXISTS gate_log_gate_name_check;

UPDATE gate_log SET gate_name = LOWER(gate_name);

-- Add new lowercase CHECK constraint
ALTER TABLE gate_log ADD CONSTRAINT gate_log_gate_name_check CHECK (
    gate_name IN (
        'g0_ingestion', 'g1_retrieval', 'g2_citation', 'g2.5_grounding',
        'g3_format', 'g4_novelty', 'g5_image', 'g5_commit',
        'coverage_sensor', 'cost_gate'
    )
);

-- Store canonical gate names in config for Python to load
INSERT INTO config (key, value, value_type, category, description) VALUES
    ('valid_gate_names',
     'g0_ingestion,g1_retrieval,g2_citation,g2.5_grounding,g3_format,g4_novelty,g5_image,g5_commit,coverage_sensor,cost_gate',
     'csv', 'gates', 'Canonical gate names (loaded by Python at startup)')
ON CONFLICT (key) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- C. Update fn_commit_slide gate name strings to lowercase
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION fn_commit_slide(
    p_deck_id UUID,
    p_slide_no INT,
    p_slide_spec JSONB,
    p_run_id UUID DEFAULT gen_random_uuid(),
    p_novelty_passed BOOLEAN DEFAULT NULL,
    p_novelty_score FLOAT DEFAULT NULL,
    p_grounding_passed BOOLEAN DEFAULT NULL,
    p_grounding_score FLOAT DEFAULT NULL,
    p_image_id UUID DEFAULT NULL
)
RETURNS TABLE (
    success BOOLEAN,
    slide_id UUID,
    errors JSONB
) AS $$
DECLARE
    v_structure_valid BOOLEAN;
    v_structure_errors JSONB;
    v_citations_valid BOOLEAN;
    v_citations_errors JSONB;
    v_all_errors JSONB := '[]'::jsonb;
    v_slide_id UUID;
    v_intent slide_intent;
    v_expected_type slide_type;
    v_declared_type slide_type;
BEGIN
    -- G2: Validate citations
    SELECT vc.is_valid, vc.errors INTO v_citations_valid, v_citations_errors
    FROM fn_validate_citations(p_slide_spec) vc;

    IF NOT v_citations_valid THEN
        v_all_errors := v_all_errors || v_citations_errors;
    END IF;

    INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, reason, payload)
    VALUES (p_run_id, p_deck_id, p_slide_no, 'g2_citation',
            CASE WHEN v_citations_valid THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN v_citations_valid THEN 'Citations valid' ELSE 'Citation errors' END,
            jsonb_build_object('errors', COALESCE(v_citations_errors, '[]'::jsonb)));

    -- G2.5: Log grounding result
    IF p_grounding_passed IS NOT NULL THEN
        INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, score, threshold, reason)
        VALUES (p_run_id, p_deck_id, p_slide_no, 'g2.5_grounding',
                CASE WHEN p_grounding_passed THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
                p_grounding_score, 0.3,
                CASE WHEN p_grounding_passed THEN 'All bullets grounded in sources' ELSE 'Ungrounded bullets detected' END);

        IF NOT p_grounding_passed THEN
            v_all_errors := v_all_errors || '["Grounding check failed (G2.5)"]'::jsonb;
        END IF;
    END IF;

    -- G3: Validate structure
    SELECT vs.is_valid, vs.errors INTO v_structure_valid, v_structure_errors
    FROM fn_validate_slide_structure(p_slide_spec) vs;

    IF NOT v_structure_valid THEN
        v_all_errors := v_all_errors || v_structure_errors;
    END IF;

    INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, reason, payload)
    VALUES (p_run_id, p_deck_id, p_slide_no, 'g3_format',
            CASE WHEN v_structure_valid THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN v_structure_valid THEN 'Format valid' ELSE 'Format errors' END,
            jsonb_build_object('errors', COALESCE(v_structure_errors, '[]'::jsonb)));

    -- G4: Log novelty result
    IF p_novelty_passed IS NOT NULL THEN
        INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, score, threshold, reason)
        VALUES (p_run_id, p_deck_id, p_slide_no, 'g4_novelty',
                CASE WHEN p_novelty_passed THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
                p_novelty_score, 0.85,
                CASE WHEN p_novelty_passed THEN 'Content is novel' ELSE 'Too similar to existing slide' END);

        IF NOT p_novelty_passed THEN
            v_all_errors := v_all_errors || '["Novelty check failed (G4)"]'::jsonb;
        END IF;
    END IF;

    -- G5: Final commit gate
    INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, reason, payload)
    VALUES (p_run_id, p_deck_id, p_slide_no, 'g5_commit',
            CASE WHEN jsonb_array_length(v_all_errors) = 0 THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN jsonb_array_length(v_all_errors) = 0 THEN 'All gates passed' ELSE 'Gate failures' END,
            jsonb_build_object('errors', v_all_errors, 'gates_logged', ARRAY['G2', 'G2.5', 'G3', 'G4', 'G5']));

    IF jsonb_array_length(v_all_errors) > 0 THEN
        RETURN QUERY SELECT false, NULL::UUID, v_all_errors;
        RETURN;
    END IF;

    v_intent := (p_slide_spec->>'intent')::slide_intent;

    SELECT itm.slide_type INTO v_expected_type
    FROM intent_type_map itm WHERE itm.intent = v_intent;

    v_expected_type := COALESCE(v_expected_type, 'bullets'::slide_type);

    v_declared_type := COALESCE(
        (p_slide_spec->>'slide_type')::slide_type,
        v_expected_type
    );
    IF v_declared_type != v_expected_type THEN
        v_all_errors := v_all_errors || jsonb_build_array(
            format('slide_type mismatch: got %s, expected %s for intent %s',
                   v_declared_type, v_expected_type, v_intent));
        RETURN QUERY SELECT false, NULL::UUID, v_all_errors;
        RETURN;
    END IF;

    INSERT INTO slide (
        deck_id, slide_no, intent, title, bullets,
        speaker_notes, citations, image_id,
        slide_type, content_data
    ) VALUES (
        p_deck_id,
        p_slide_no,
        v_intent,
        p_slide_spec->>'title',
        p_slide_spec->'bullets',
        p_slide_spec->>'speaker_notes',
        p_slide_spec->'citations',
        p_image_id,
        COALESCE((p_slide_spec->>'slide_type')::slide_type, 'bullets'::slide_type),
        COALESCE(p_slide_spec->'content_data', '{}'::jsonb)
    )
    ON CONFLICT (deck_id, slide_no) DO UPDATE SET
        intent = EXCLUDED.intent,
        title = EXCLUDED.title,
        bullets = EXCLUDED.bullets,
        speaker_notes = EXCLUDED.speaker_notes,
        citations = EXCLUDED.citations,
        image_id = EXCLUDED.image_id,
        slide_type = EXCLUDED.slide_type,
        content_data = EXCLUDED.content_data,
        retry_count = slide.retry_count + 1,
        updated_at = now()
    RETURNING slide.slide_id INTO v_slide_id;

    RETURN QUERY SELECT true, v_slide_id, '[]'::jsonb;
END;
$$ LANGUAGE plpgsql VOLATILE
   SECURITY INVOKER
   SET search_path = public;


-- ─────────────────────────────────────────────────────────────────────────────
-- D. Fix fn_check_grounding default threshold (was 0.7, should be 0.3)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION fn_check_grounding(
    p_slide_spec JSONB,
    p_bullet_embeddings VECTOR(1536)[],
    p_threshold FLOAT DEFAULT 0.3,
    p_run_id UUID DEFAULT gen_random_uuid()
)
RETURNS TABLE (
    is_grounded BOOLEAN,
    ungrounded_bullets INT[],
    min_similarity FLOAT,
    grounding_details JSONB
) AS $$
DECLARE
    v_citations JSONB;
    v_chunk_ids UUID[];
    v_ungrounded INT[] := '{}';
    v_min_sim FLOAT := 1.0;
    v_bullet_idx INT;
    v_bullet_embedding VECTOR(1536);
    v_max_sim FLOAT;
    v_details JSONB := '[]'::jsonb;
BEGIN
    v_citations := p_slide_spec->'citations';
    IF v_citations IS NULL OR jsonb_typeof(v_citations) != 'array' THEN
        FOR v_bullet_idx IN 1..array_length(p_bullet_embeddings, 1) LOOP
            v_ungrounded := array_append(v_ungrounded, v_bullet_idx);
        END LOOP;
        RETURN QUERY SELECT false, v_ungrounded, 0.0::FLOAT,
            '{"error": "No citations provided"}'::jsonb;
        RETURN;
    END IF;

    SELECT ARRAY_AGG((c.val->>'chunk_id')::UUID) INTO v_chunk_ids
    FROM jsonb_array_elements(v_citations) AS c(val)
    WHERE c.val->>'chunk_id' IS NOT NULL;

    IF v_chunk_ids IS NULL OR array_length(v_chunk_ids, 1) = 0 THEN
        FOR v_bullet_idx IN 1..array_length(p_bullet_embeddings, 1) LOOP
            v_ungrounded := array_append(v_ungrounded, v_bullet_idx);
        END LOOP;
        RETURN QUERY SELECT false, v_ungrounded, 0.0::FLOAT,
            '{"error": "No valid chunk_ids in citations"}'::jsonb;
        RETURN;
    END IF;

    FOR v_bullet_idx IN 1..array_length(p_bullet_embeddings, 1) LOOP
        v_bullet_embedding := p_bullet_embeddings[v_bullet_idx];

        SELECT MAX(1 - (v_bullet_embedding <=> c.embedding)) INTO v_max_sim
        FROM chunk c
        WHERE c.chunk_id = ANY(v_chunk_ids)
          AND c.embedding IS NOT NULL;

        v_max_sim := COALESCE(v_max_sim, 0.0);

        IF v_max_sim < v_min_sim THEN
            v_min_sim := v_max_sim;
        END IF;

        v_details := v_details || jsonb_build_array(jsonb_build_object(
            'bullet_index', v_bullet_idx,
            'max_similarity', ROUND(v_max_sim::numeric, 4),
            'grounded', v_max_sim >= p_threshold
        ));

        IF v_max_sim < p_threshold THEN
            v_ungrounded := array_append(v_ungrounded, v_bullet_idx);
        END IF;
    END LOOP;

    RETURN QUERY SELECT
        array_length(v_ungrounded, 1) IS NULL OR array_length(v_ungrounded, 1) = 0,
        v_ungrounded,
        v_min_sim,
        v_details;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE
   SET search_path = public;

COMMIT;
