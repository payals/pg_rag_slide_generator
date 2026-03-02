-- =============================================================================
-- Rollback for Migration 010: Schema Consolidation & Safety Hardening
-- =============================================================================
--
-- Reverses all changes from 010_consolidate_config.sql.
-- Safe: only drops things that were added; never modifies original data.
--
-- Run with: psql -d slidegen -f db/migrations/010_consolidate_config_rollback.sql
-- =============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- Drop new tables (in dependency order — tables with no dependents first)
-- ─────────────────────────────────────────────────────────────────────────────

DROP TABLE IF EXISTS prompt_template CASCADE;
DROP TABLE IF EXISTS slide_type_config CASCADE;
DROP TABLE IF EXISTS section_divider CASCADE;
DROP TABLE IF EXISTS static_slide CASCADE;
DROP TABLE IF EXISTS theme CASCADE;
DROP TABLE IF EXISTS generation_run CASCADE;

-- ─────────────────────────────────────────────────────────────────────────────
-- Remove new columns from intent_type_map
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE intent_type_map DROP COLUMN IF EXISTS sort_order;
ALTER TABLE intent_type_map DROP COLUMN IF EXISTS suggested_title;
ALTER TABLE intent_type_map DROP COLUMN IF EXISTS requirements;
ALTER TABLE intent_type_map DROP COLUMN IF EXISTS is_generatable;
ALTER TABLE intent_type_map DROP COLUMN IF EXISTS related_intents;

-- Remove title/thanks rows that were added to intent_type_map
-- (they did not exist before this migration)
DELETE FROM intent_type_map WHERE intent IN ('title', 'thanks');

-- ─────────────────────────────────────────────────────────────────────────────
-- Remove deck.status column and enum
-- ─────────────────────────────────────────────────────────────────────────────

DROP INDEX IF EXISTS idx_deck_active_generation;
ALTER TABLE deck DROP COLUMN IF EXISTS status;
DROP TYPE IF EXISTS deck_status;

-- ─────────────────────────────────────────────────────────────────────────────
-- Remove run_status enum
-- ─────────────────────────────────────────────────────────────────────────────

DROP TYPE IF EXISTS run_status;

-- ─────────────────────────────────────────────────────────────────────────────
-- Remove gate_log constraint
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE gate_log DROP CONSTRAINT IF EXISTS gate_log_gate_name_check;

-- ─────────────────────────────────────────────────────────────────────────────
-- Remove new index
-- ─────────────────────────────────────────────────────────────────────────────

DROP INDEX IF EXISTS idx_slide_content_embedding;

-- ─────────────────────────────────────────────────────────────────────────────
-- Remove updated_at triggers
-- ─────────────────────────────────────────────────────────────────────────────

DROP TRIGGER IF EXISTS doc_updated_at ON doc;
DROP TRIGGER IF EXISTS deck_updated_at ON deck;

-- ─────────────────────────────────────────────────────────────────────────────
-- Restore original fn_pick_next_intent with hardcoded array
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION fn_pick_next_intent(
    p_deck_id UUID,
    p_exclude slide_intent[] DEFAULT '{}'
)
RETURNS slide_intent AS $$
DECLARE
    v_intent_order slide_intent[] := ARRAY[
        'problem', 'why-postgres', 'comparison', 'capabilities',
        'thesis', 'schema-security', 'architecture', 'what-is-rag',
        'rag-in-postgres', 'what-is-mcp', 'mcp-tools', 'gates',
        'observability', 'what-we-built', 'takeaways'
    ]::slide_intent[];
    v_next slide_intent;
BEGIN
    SELECT i.intent INTO v_next
    FROM unnest(v_intent_order) WITH ORDINALITY AS i(intent, ord)
    WHERE NOT EXISTS (
        SELECT 1 FROM slide s
        WHERE s.deck_id = p_deck_id AND s.intent = i.intent
    )
    AND i.intent != ALL(p_exclude)
    ORDER BY i.ord
    LIMIT 1;
    RETURN v_next;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE
   SET search_path = public;

-- ─────────────────────────────────────────────────────────────────────────────
-- Restore original v_deck_coverage with hardcoded array
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_deck_coverage AS
SELECT
    d.deck_id,
    d.topic,
    d.target_slides,
    COUNT(DISTINCT s.intent) AS covered_intents,
    COUNT(s.slide_id) AS total_slides,
    ARRAY_AGG(DISTINCT s.intent ORDER BY s.intent) FILTER (WHERE s.intent IS NOT NULL) AS covered,
    ARRAY(
        SELECT i.intent
        FROM unnest(ARRAY['problem', 'why-postgres', 'comparison', 'capabilities',
                          'thesis', 'schema-security', 'architecture', 'what-is-rag',
                          'rag-in-postgres', 'what-is-mcp', 'mcp-tools', 'gates',
                          'observability', 'what-we-built', 'takeaways']::slide_intent[]) AS i(intent)
        WHERE NOT EXISTS (
            SELECT 1 FROM slide s2
            WHERE s2.deck_id = d.deck_id AND s2.intent = i.intent
        )
    ) AS missing
FROM deck d
LEFT JOIN slide s ON d.deck_id = s.deck_id
GROUP BY d.deck_id, d.topic, d.target_slides;

-- ─────────────────────────────────────────────────────────────────────────────
-- Restore original v_deck_health with correlated subqueries
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_deck_health AS
SELECT
    d.deck_id,
    d.topic,
    COUNT(s.slide_id) AS slide_count,
    d.target_slides,
    COALESCE(SUM(s.retry_count), 0) AS total_retries,
    ROUND(AVG(s.retry_count)::numeric, 2) AS avg_retries_per_slide,
    (SELECT COUNT(*) FROM gate_log g
     WHERE g.deck_id = d.deck_id AND g.decision = 'fail') AS total_gate_failures,
    (SELECT COUNT(DISTINCT g.slide_no) FROM gate_log g
     WHERE g.deck_id = d.deck_id AND g.decision = 'fail') AS slides_with_failures,
    ROUND(
        (COUNT(s.slide_id)::float / NULLIF(d.target_slides, 0) * 100)::numeric, 1
    ) AS completion_pct
FROM deck d
LEFT JOIN slide s ON d.deck_id = s.deck_id
GROUP BY d.deck_id, d.topic, d.target_slides;

-- ─────────────────────────────────────────────────────────────────────────────
-- Restore original v_top_sources with text cast on indexed side
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_top_sources AS
WITH citation_chunks AS (
    SELECT
        s.deck_id,
        jsonb_array_elements(s.citations)->>'chunk_id' AS chunk_id
    FROM slide s
    WHERE s.citations IS NOT NULL AND jsonb_array_length(s.citations) > 0
)
SELECT
    cc.deck_id,
    c.chunk_id,
    d.doc_id,
    d.title AS doc_title,
    d.doc_type,
    d.trust_level,
    COUNT(*) AS citation_count
FROM citation_chunks cc
JOIN chunk c ON c.chunk_id::text = cc.chunk_id
JOIN doc d ON c.doc_id = d.doc_id
GROUP BY cc.deck_id, c.chunk_id, d.doc_id, d.title, d.doc_type, d.trust_level
ORDER BY cc.deck_id, citation_count DESC;

-- ─────────────────────────────────────────────────────────────────────────────
-- Restore original update_slide_content_text (without new fields)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_slide_content_text() RETURNS TRIGGER AS $$
BEGIN
    NEW.content_text := NEW.title || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(NEW.bullets)), ' '), '') || ' ' ||
        COALESCE(NEW.content_data->>'statement', '') || ' ' ||
        COALESCE(NEW.content_data->>'subtitle', '') || ' ' ||
        COALESCE(NEW.content_data->>'code_block', '') || ' ' ||
        COALESCE(NEW.content_data->>'caption', '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(
                COALESCE(NEW.content_data->'left_items', '[]'::jsonb))), ' '), '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(
                COALESCE(NEW.content_data->'right_items', '[]'::jsonb))), ' '), '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT e->>'label' FROM jsonb_array_elements(
                COALESCE(NEW.content_data->'steps', '[]'::jsonb)) AS e), ' '), '') || ' ' ||
        COALESCE(NEW.speaker_notes, '');
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
   SECURITY INVOKER
   SET search_path = public;

-- Refresh content_text with original field set
UPDATE slide SET content_data = content_data;

-- ─────────────────────────────────────────────────────────────────────────────
-- Drop helper functions (CASCADE drops their triggers)
-- ─────────────────────────────────────────────────────────────────────────────

DROP FUNCTION IF EXISTS fn_set_updated_at() CASCADE;
DROP FUNCTION IF EXISTS fn_validate_type_config() CASCADE;

-- ─────────────────────────────────────────────────────────────────────────────
-- Remove table comments
-- ─────────────────────────────────────────────────────────────────────────────

COMMENT ON TABLE gate_log IS NULL;
COMMENT ON TABLE retrieval_log IS NULL;

DO $$
BEGIN
    RAISE NOTICE '✓ Rollback of migration 010 complete';
    RAISE NOTICE '  Dropped: static_slide, section_divider, theme, slide_type_config, prompt_template, generation_run';
    RAISE NOTICE '  Removed: intent_type_map extensions, deck.status, gate_log constraint';
    RAISE NOTICE '  Restored: fn_pick_next_intent, v_deck_coverage, v_deck_health, v_top_sources, update_slide_content_text';
END $$;

COMMIT;
