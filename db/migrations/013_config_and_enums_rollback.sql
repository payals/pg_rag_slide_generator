-- =============================================================================
-- Rollback for Migration 013: Config table, gate-name normalization
-- =============================================================================

BEGIN;

-- Drop config table
DROP TABLE IF EXISTS config;

-- Restore mixed-case gate names
UPDATE gate_log SET gate_name = CASE gate_name
    WHEN 'g0_ingestion'     THEN 'G0_ingestion'
    WHEN 'g1_retrieval'     THEN 'G1_retrieval'
    WHEN 'g2_citation'      THEN 'G2_citation'
    WHEN 'g2.5_grounding'   THEN 'G2.5_grounding'
    WHEN 'g3_format'        THEN 'G3_format'
    WHEN 'g4_novelty'       THEN 'G4_novelty'
    WHEN 'g5_image'         THEN 'G5_IMAGE'
    WHEN 'g5_commit'        THEN 'G5_commit'
    WHEN 'coverage_sensor'  THEN 'COVERAGE_SENSOR'
    WHEN 'cost_gate'        THEN 'COST_GATE'
    ELSE gate_name
END;

-- Restore old CHECK constraint
ALTER TABLE gate_log DROP CONSTRAINT IF EXISTS gate_log_gate_name_check;
ALTER TABLE gate_log ADD CONSTRAINT gate_log_gate_name_check CHECK (
    gate_name IN (
        'G0_ingestion', 'G1_retrieval', 'G2_citation', 'G2.5_grounding',
        'G3_format', 'G4_novelty', 'G5_IMAGE', 'G5_commit',
        'COVERAGE_SENSOR', 'COST_GATE'
    )
);

-- Restore fn_check_grounding default threshold to 0.7
-- (full function body omitted -- re-run schema.sql to restore)

-- Restore fn_commit_slide with mixed-case gate names
-- (full function body omitted -- re-run schema.sql to restore)

COMMIT;
