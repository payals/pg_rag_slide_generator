-- Migration 015: Move G1 retrieval quality gate into Postgres
--
-- Previously G1 was the only gate evaluated in Python (orchestrator.py).
-- This migration creates fn_check_retrieval_quality so ALL gates
-- are now PL/pgSQL functions, matching the "Postgres as control plane" thesis.

-- ─────────────────────────────────────────────────────────────────────────────
-- A. Add G1 config keys to the config table
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO config (key, value, value_type, category, description) VALUES
    ('g1_min_chunks',  '3',   'int',   'gates', 'G1: minimum chunks required from retrieval'),
    ('g1_min_score',   '0.3', 'float', 'gates', 'G1: minimum combined_score of top result')
ON CONFLICT (key) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- B. Create fn_check_retrieval_quality
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION fn_check_retrieval_quality(
    p_search_results JSONB,
    p_min_chunks INT DEFAULT 3,
    p_min_score FLOAT DEFAULT 0.3
)
RETURNS TABLE (
    is_valid BOOLEAN,
    chunk_count INT,
    top_score FLOAT,
    errors JSONB
) AS $$
DECLARE
    v_errors JSONB := '[]'::jsonb;
    v_count INT;
    v_top_score FLOAT;
BEGIN
    IF p_search_results IS NULL OR jsonb_typeof(p_search_results) != 'array' THEN
        v_count := 0;
        v_top_score := 0.0;
    ELSE
        v_count := jsonb_array_length(p_search_results);
        IF v_count > 0 THEN
            v_top_score := COALESCE(
                (p_search_results->0->>'combined_score')::FLOAT,
                0.0
            );
        ELSE
            v_top_score := 0.0;
        END IF;
    END IF;

    IF v_count < p_min_chunks THEN
        v_errors := v_errors || jsonb_build_array(
            format('Too few chunks: %s (min: %s)', v_count, p_min_chunks)
        );
    END IF;

    IF v_top_score <= p_min_score THEN
        v_errors := v_errors || jsonb_build_array(
            format('Top score too low: %s (min: %s)', round(v_top_score::numeric, 3), round(p_min_score::numeric, 3))
        );
    END IF;

    RETURN QUERY SELECT
        jsonb_array_length(v_errors) = 0 AS is_valid,
        v_count AS chunk_count,
        v_top_score AS top_score,
        v_errors AS errors;
END;
$$ LANGUAGE plpgsql IMMUTABLE
   SECURITY INVOKER
   PARALLEL SAFE
   SET search_path = public;
