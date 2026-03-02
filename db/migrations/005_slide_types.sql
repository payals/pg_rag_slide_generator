-- Migration 005: Add slide_type system
-- Adds: slide_type enum, content_data column, intent_type_map table
-- Updates: fn_commit_slide, update_slide_content_text trigger

-- 1. Create slide_type enum
CREATE TYPE slide_type AS ENUM (
    'statement', 'bullets', 'split', 'flow', 'diagram', 'code'
);

-- 2. Add new columns to slide table
ALTER TABLE slide ADD COLUMN slide_type slide_type NOT NULL DEFAULT 'bullets';
ALTER TABLE slide ADD COLUMN content_data JSONB DEFAULT '{}'::jsonb;

-- 3. Intent-to-type mapping table (the control plane)
CREATE TABLE intent_type_map (
    intent        slide_intent PRIMARY KEY,
    slide_type    slide_type NOT NULL,
    require_image BOOLEAN NOT NULL DEFAULT false
);

INSERT INTO intent_type_map (intent, slide_type, require_image) VALUES
    ('problem',         'bullets',   false),
    ('why-postgres',    'bullets',   false),
    ('comparison',      'split',     false),
    ('capabilities',    'bullets',   false),
    ('thesis',          'statement', false),
    ('schema-security', 'bullets',   false),
    ('architecture',    'diagram',   true),
    ('what-is-rag',     'diagram',   true),
    ('rag-in-postgres', 'code',      false),
    ('what-is-mcp',     'diagram',   true),
    ('mcp-tools',       'code',      false),
    ('gates',           'flow',      false),
    ('observability',   'code',      false),
    ('what-we-built',   'bullets',   false),
    ('takeaways',       'bullets',   false);

-- 4. Update fn_commit_slide to store slide_type and content_data
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
    VALUES (p_run_id, p_deck_id, p_slide_no, 'G2_citation',
            CASE WHEN v_citations_valid THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN v_citations_valid THEN 'Citations valid' ELSE 'Citation errors' END,
            jsonb_build_object('errors', COALESCE(v_citations_errors, '[]'::jsonb)));
    
    -- G2.5: Log grounding result
    IF p_grounding_passed IS NOT NULL THEN
        INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, score, threshold, reason)
        VALUES (p_run_id, p_deck_id, p_slide_no, 'G2.5_grounding',
                CASE WHEN p_grounding_passed THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
                p_grounding_score, 0.7,
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
    VALUES (p_run_id, p_deck_id, p_slide_no, 'G3_format',
            CASE WHEN v_structure_valid THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN v_structure_valid THEN 'Format valid' ELSE 'Format errors' END,
            jsonb_build_object('errors', COALESCE(v_structure_errors, '[]'::jsonb)));
    
    -- G4: Log novelty result
    IF p_novelty_passed IS NOT NULL THEN
        INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, score, threshold, reason)
        VALUES (p_run_id, p_deck_id, p_slide_no, 'G4_novelty',
                CASE WHEN p_novelty_passed THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
                p_novelty_score, 0.85,
                CASE WHEN p_novelty_passed THEN 'Content is novel' ELSE 'Too similar to existing slide' END);
        
        IF NOT p_novelty_passed THEN
            v_all_errors := v_all_errors || '["Novelty check failed (G4)"]'::jsonb;
        END IF;
    END IF;
    
    -- G5: Final commit gate
    INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, reason, payload)
    VALUES (p_run_id, p_deck_id, p_slide_no, 'G5_commit',
            CASE WHEN jsonb_array_length(v_all_errors) = 0 THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN jsonb_array_length(v_all_errors) = 0 THEN 'All gates passed' ELSE 'Gate failures' END,
            jsonb_build_object('errors', v_all_errors, 'gates_logged', ARRAY['G2', 'G2.5', 'G3', 'G4', 'G5']));
    
    IF jsonb_array_length(v_all_errors) > 0 THEN
        RETURN QUERY SELECT false, NULL::UUID, v_all_errors;
        RETURN;
    END IF;
    
    -- Parse intent
    v_intent := (p_slide_spec->>'intent')::slide_intent;

    -- Resolve expected slide_type from intent_type_map
    SELECT itm.slide_type INTO v_expected_type
    FROM intent_type_map itm WHERE itm.intent = v_intent;

    v_expected_type := COALESCE(v_expected_type, 'bullets'::slide_type);

    -- Validate: if caller declared a slide_type, it must match the DB mapping
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

    -- Insert or update slide
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
        v_expected_type,
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

-- 5. Update content_text trigger to include content_data fields
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

-- Update the trigger to fire on content_data changes too
DROP TRIGGER IF EXISTS slide_content_text_update ON slide;
CREATE TRIGGER slide_content_text_update
    BEFORE INSERT OR UPDATE OF title, bullets, speaker_notes, content_data ON slide
    FOR EACH ROW EXECUTE FUNCTION update_slide_content_text();
