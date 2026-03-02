-- Migration 021: Normalize Gate Names to Lowercase
--
-- Migration 020 introduced uppercase gate names in fn_commit_slide and the
-- orchestrator. This migration reverts to the original lowercase convention
-- used by the CHECK constraint, ensuring consistency across all layers.

-- 1. Drop any existing constraint (may be uppercase or lowercase)
ALTER TABLE gate_log DROP CONSTRAINT IF EXISTS gate_log_gate_name_check;

-- 2. Normalize any uppercase gate names back to lowercase
UPDATE gate_log SET gate_name = CASE gate_name
    WHEN 'G1_retrieval'    THEN 'g1_retrieval'
    WHEN 'G2_citation'     THEN 'g2_citation'
    WHEN 'G2.5_grounding'  THEN 'g2.5_grounding'
    WHEN 'G3_format'       THEN 'g3_format'
    WHEN 'G4_novelty'      THEN 'g4_novelty'
    WHEN 'G5_image'        THEN 'g5_image'
    WHEN 'G5_commit'       THEN 'g5_commit'
    WHEN 'COVERAGE_SENSOR' THEN 'coverage_sensor'
    ELSE gate_name
END
WHERE gate_name IN (
    'G1_retrieval', 'G2_citation', 'G2.5_grounding',
    'G3_format', 'G4_novelty', 'G5_image', 'G5_commit',
    'COVERAGE_SENSOR'
);

-- 3. Re-add the original lowercase constraint
ALTER TABLE gate_log ADD CONSTRAINT gate_log_gate_name_check CHECK (
    gate_name = ANY (ARRAY[
        'g0_ingestion',
        'g1_retrieval',
        'g2_citation',
        'g2.5_grounding',
        'g3_format',
        'g4_novelty',
        'g5_image',
        'g5_commit',
        'coverage_sensor',
        'cost_gate'
    ])
);
