-- Migration 020: Gate Failure Logging
--
-- Moves G2/G2.5/G3/G4 gate logging out of fn_commit_slide and into the
-- orchestrator (via fn_log_gate). fn_commit_slide retains only G5 (commit gate)
-- since only it knows the final trust-but-verify outcome.
--
-- Also adds p_draft_retries so slide.retry_count reflects actual draft retries
-- rather than commit-overwrite count.

-- Drop the old 9-param overload so callers always resolve to the new signature.
DROP FUNCTION IF EXISTS fn_commit_slide(UUID, INT, JSONB, UUID, BOOLEAN, FLOAT, BOOLEAN, FLOAT, UUID);

CREATE OR REPLACE FUNCTION fn_commit_slide(
    p_deck_id UUID,
    p_slide_no INT,
    p_slide_spec JSONB,
    p_run_id UUID DEFAULT gen_random_uuid(),
    p_novelty_passed BOOLEAN DEFAULT NULL,
    p_novelty_score FLOAT DEFAULT NULL,
    p_grounding_passed BOOLEAN DEFAULT NULL,
    p_grounding_score FLOAT DEFAULT NULL,
    p_image_id UUID DEFAULT NULL,
    p_draft_retries INT DEFAULT 0
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
    -- G2: Validate citations (trust-but-verify, result NOT logged here)
    SELECT vc.is_valid, vc.errors INTO v_citations_valid, v_citations_errors
    FROM fn_validate_citations(p_slide_spec) vc;

    IF NOT v_citations_valid THEN
        v_all_errors := v_all_errors || v_citations_errors;
    END IF;

    -- G2.5: Accumulate grounding errors (logged by orchestrator)
    IF p_grounding_passed IS NOT NULL AND NOT p_grounding_passed THEN
        v_all_errors := v_all_errors || '["Grounding check failed (G2.5)"]'::jsonb;
    END IF;

    -- G3: Validate structure (trust-but-verify, result NOT logged here)
    SELECT vs.is_valid, vs.errors INTO v_structure_valid, v_structure_errors
    FROM fn_validate_slide_structure(p_slide_spec) vs;

    IF NOT v_structure_valid THEN
        v_all_errors := v_all_errors || v_structure_errors;
    END IF;

    -- G4: Accumulate novelty errors (logged by orchestrator)
    IF p_novelty_passed IS NOT NULL AND NOT p_novelty_passed THEN
        v_all_errors := v_all_errors || '["Novelty check failed (G4)"]'::jsonb;
    END IF;

    -- G5: Final commit gate (only gate logged by fn_commit_slide)
    INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, reason, payload)
    VALUES (p_run_id, p_deck_id, p_slide_no, 'g5_commit',
            CASE WHEN jsonb_array_length(v_all_errors) = 0 THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN jsonb_array_length(v_all_errors) = 0 THEN 'All gates passed' ELSE 'Gate failures' END,
            jsonb_build_object('errors', v_all_errors, 'gates_logged', ARRAY['G5']));

    -- If any validation failed, return errors
    IF jsonb_array_length(v_all_errors) > 0 THEN
        RETURN QUERY SELECT false, NULL::UUID, v_all_errors;
        RETURN;
    END IF;

    -- Parse intent
    v_intent := (p_slide_spec->>'intent')::slide_intent;

    -- Resolve expected slide_type from intent_type_map
    SELECT (itm.value->>'slide_type')::slide_type
    INTO v_expected_type
    FROM jsonb_each(
        (SELECT style_contract->'intent_type_map'
         FROM deck WHERE deck_id = p_deck_id)
    ) itm
    WHERE itm.key = p_slide_spec->>'intent';

    v_declared_type := COALESCE(
        (p_slide_spec->>'slide_type')::slide_type,
        v_expected_type,
        'bullets'::slide_type
    );

    -- Insert or update slide
    INSERT INTO slide (
        deck_id, slide_no, intent, title, bullets,
        speaker_notes, citations, image_id,
        slide_type, content_data, retry_count
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
        COALESCE(p_slide_spec->'content_data', '{}'::jsonb),
        p_draft_retries
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
        retry_count = p_draft_retries,
        updated_at = now()
    RETURNING slide.slide_id INTO v_slide_id;

    RETURN QUERY SELECT true, v_slide_id, '[]'::jsonb;
END;
$$ LANGUAGE plpgsql VOLATILE
   SECURITY INVOKER
   SET search_path = public;
