-- Migration 004: Tighten bullet constraints
-- Changes: min 3→2, max 5→3, max words 25→15
-- Rationale: reduce visual density on slides

CREATE OR REPLACE FUNCTION fn_validate_slide_structure(
    p_slide_spec JSONB,
    p_min_bullets INT DEFAULT 2,
    p_max_bullets INT DEFAULT 3,
    p_max_bullet_words INT DEFAULT 15
)
RETURNS TABLE (
    is_valid BOOLEAN,
    errors JSONB
) AS $$
DECLARE
    v_errors JSONB := '[]'::jsonb;
    v_bullets JSONB;
    v_bullet TEXT;
    v_bullet_count INT;
    v_word_count INT;
    v_i INT;
BEGIN
    -- Check required fields
    IF p_slide_spec->>'title' IS NULL OR trim(p_slide_spec->>'title') = '' THEN
        v_errors := v_errors || '["Missing or empty title"]'::jsonb;
    END IF;
    
    IF p_slide_spec->>'intent' IS NULL THEN
        v_errors := v_errors || '["Missing intent"]'::jsonb;
    END IF;
    
    -- Check bullets
    v_bullets := p_slide_spec->'bullets';
    IF v_bullets IS NULL OR jsonb_typeof(v_bullets) != 'array' THEN
        v_errors := v_errors || '["bullets must be an array"]'::jsonb;
    ELSE
        v_bullet_count := jsonb_array_length(v_bullets);
        
        IF v_bullet_count < p_min_bullets THEN
            v_errors := v_errors || jsonb_build_array(
                format('Too few bullets: %s (min: %s)', v_bullet_count, p_min_bullets)
            );
        END IF;
        
        IF v_bullet_count > p_max_bullets THEN
            v_errors := v_errors || jsonb_build_array(
                format('Too many bullets: %s (max: %s)', v_bullet_count, p_max_bullets)
            );
        END IF;
        
        -- Check each bullet length
        FOR v_i IN 0..v_bullet_count - 1 LOOP
            v_bullet := v_bullets->>v_i;
            IF v_bullet IS NOT NULL THEN
                v_word_count := array_length(regexp_split_to_array(trim(v_bullet), '\s+'), 1);
                IF v_word_count > p_max_bullet_words THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Bullet %s too long: %s words (max: %s)', v_i + 1, v_word_count, p_max_bullet_words)
                    );
                END IF;
            END IF;
        END LOOP;
    END IF;
    
    -- Check speaker notes for content slides (not title/thanks)
    IF p_slide_spec->>'intent' IS NOT NULL 
       AND p_slide_spec->>'intent' NOT IN ('title', 'thanks') THEN
        IF p_slide_spec->>'speaker_notes' IS NULL 
           OR length(trim(p_slide_spec->>'speaker_notes')) < 50 THEN
            v_errors := v_errors || jsonb_build_array(
                'Speaker notes required for content slides (min 50 characters)'
            );
        END IF;
    END IF;
    
    RETURN QUERY SELECT 
        jsonb_array_length(v_errors) = 0 AS is_valid,
        v_errors AS errors;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL SAFE
   SET search_path = public;
