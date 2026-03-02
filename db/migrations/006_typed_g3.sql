-- Migration 006: Type-aware G3 validation
-- Rewrites fn_validate_slide_structure to dispatch validation by slide_type
-- The DB resolves slide_type from intent_type_map internally

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
    v_slide_type TEXT;
    v_bullets JSONB;
    v_bullet TEXT;
    v_bullet_count INT;
    v_word_count INT;
    v_i INT;
    v_cd JSONB;
    v_title TEXT;
    v_title_len INT;
    v_item TEXT;
    v_items JSONB;
    v_steps JSONB;
    v_step JSONB;
    v_code TEXT;
    v_lines TEXT[];
    v_line TEXT;
BEGIN
    -- Check required fields
    v_title := p_slide_spec->>'title';
    IF v_title IS NULL OR trim(v_title) = '' THEN
        v_errors := v_errors || '["Missing or empty title"]'::jsonb;
    ELSE
        v_title_len := length(v_title);
        IF v_title_len > 60 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Title too long: %s chars (max: 60)', v_title_len));
        END IF;
        IF v_title ~ '\.$' THEN
            v_errors := v_errors || '["Title should not end with a period"]'::jsonb;
        END IF;
    END IF;

    IF p_slide_spec->>'intent' IS NULL THEN
        v_errors := v_errors || '["Missing intent"]'::jsonb;
    END IF;

    -- Resolve slide_type from intent_type_map (DB is authority)
    SELECT itm.slide_type::text INTO v_slide_type
    FROM intent_type_map itm
    WHERE itm.intent = (p_slide_spec->>'intent')::slide_intent;

    v_slide_type := COALESCE(v_slide_type, 'bullets');

    v_cd := COALESCE(p_slide_spec->'content_data', '{}'::jsonb);

    CASE v_slide_type

    WHEN 'statement' THEN
        -- content_data.statement required (8-90 chars)
        IF v_cd->>'statement' IS NULL OR length(trim(v_cd->>'statement')) < 8 THEN
            v_errors := v_errors || '["Statement required (min 8 chars)"]'::jsonb;
        ELSIF length(v_cd->>'statement') > 90 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Statement too long: %s chars (max: 90)', length(v_cd->>'statement')));
        END IF;
        -- subtitle optional but capped
        IF v_cd->>'subtitle' IS NOT NULL AND length(v_cd->>'subtitle') > 120 THEN
            v_errors := v_errors || '["Subtitle too long (max 120 chars)"]'::jsonb;
        END IF;
        -- bullets must be empty
        v_bullets := p_slide_spec->'bullets';
        IF v_bullets IS NOT NULL AND jsonb_typeof(v_bullets) = 'array' AND jsonb_array_length(v_bullets) > 0 THEN
            v_errors := v_errors || '["Statement slides should not have bullets"]'::jsonb;
        END IF;

    WHEN 'split' THEN
        -- left_items and right_items: 2-3 each
        v_items := COALESCE(v_cd->'left_items', '[]'::jsonb);
        IF jsonb_typeof(v_items) != 'array' OR jsonb_array_length(v_items) < 2 OR jsonb_array_length(v_items) > 3 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Split left_items must have 2-3 items (got %s)', jsonb_array_length(COALESCE(v_items, '[]'::jsonb))));
        END IF;
        v_items := COALESCE(v_cd->'right_items', '[]'::jsonb);
        IF jsonb_typeof(v_items) != 'array' OR jsonb_array_length(v_items) < 2 OR jsonb_array_length(v_items) > 3 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Split right_items must have 2-3 items (got %s)', jsonb_array_length(COALESCE(v_items, '[]'::jsonb))));
        END IF;
        -- Balance check
        IF jsonb_array_length(COALESCE(v_cd->'left_items', '[]'::jsonb)) > 0
           AND jsonb_array_length(COALESCE(v_cd->'right_items', '[]'::jsonb)) > 0
           AND abs(jsonb_array_length(v_cd->'left_items') - jsonb_array_length(v_cd->'right_items')) > 1 THEN
            v_errors := v_errors || '["Split columns must be balanced (difference <= 1)"]'::jsonb;
        END IF;

    WHEN 'flow' THEN
        -- steps: 4-7 items
        v_steps := COALESCE(v_cd->'steps', '[]'::jsonb);
        IF jsonb_typeof(v_steps) != 'array' OR jsonb_array_length(v_steps) < 4 OR jsonb_array_length(v_steps) > 7 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Flow must have 4-7 steps (got %s)', jsonb_array_length(COALESCE(v_steps, '[]'::jsonb))));
        ELSE
            FOR v_i IN 0..jsonb_array_length(v_steps) - 1 LOOP
                v_step := v_steps->v_i;
                IF v_step->>'label' IS NULL OR length(v_step->>'label') < 2 OR length(v_step->>'label') > 30 THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Flow step %s label must be 2-30 chars', v_i + 1));
                END IF;
                IF v_step->>'caption' IS NOT NULL AND length(v_step->>'caption') > 60 THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Flow step %s caption too long (max 60 chars)', v_i + 1));
                END IF;
            END LOOP;
        END IF;

    WHEN 'diagram' THEN
        -- callouts: 0-3, each <=40 chars
        v_items := COALESCE(v_cd->'callouts', '[]'::jsonb);
        IF jsonb_typeof(v_items) = 'array' AND jsonb_array_length(v_items) > 3 THEN
            v_errors := v_errors || '["Diagram callouts: max 3"]'::jsonb;
        END IF;
        IF jsonb_typeof(v_items) = 'array' THEN
            FOR v_i IN 0..jsonb_array_length(v_items) - 1 LOOP
                IF length(v_items->>v_i) > 40 THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Diagram callout %s too long: %s chars (max 40)', v_i + 1, length(v_items->>v_i)));
                END IF;
            END LOOP;
        END IF;
        -- caption optional, <=120 chars
        IF v_cd->>'caption' IS NOT NULL AND length(v_cd->>'caption') > 120 THEN
            v_errors := v_errors || '["Diagram caption too long (max 120 chars)"]'::jsonb;
        END IF;

    WHEN 'code' THEN
        -- code_block required
        v_code := v_cd->>'code_block';
        IF v_code IS NULL OR length(trim(v_code)) = 0 THEN
            v_errors := v_errors || '["Code slide requires code_block"]'::jsonb;
        ELSE
            v_lines := string_to_array(v_code, E'\n');
            IF array_length(v_lines, 1) < 4 THEN
                v_errors := v_errors || jsonb_build_array(
                    format('Code too short: %s lines (min 4)', array_length(v_lines, 1)));
            END IF;
            IF array_length(v_lines, 1) > 14 THEN
                v_errors := v_errors || jsonb_build_array(
                    format('Code too long: %s lines (max 14)', array_length(v_lines, 1)));
            END IF;
            FOREACH v_line IN ARRAY v_lines LOOP
                IF length(v_line) > 80 THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Code line exceeds 80 chars: %s', length(v_line)));
                    EXIT;
                END IF;
            END LOOP;
        END IF;
        -- language required
        IF v_cd->>'language' IS NULL THEN
            v_errors := v_errors || '["Code slide requires language field"]'::jsonb;
        END IF;
        -- explain_bullets: 0-2 items
        v_items := COALESCE(v_cd->'explain_bullets', '[]'::jsonb);
        IF jsonb_typeof(v_items) = 'array' AND jsonb_array_length(v_items) > 2 THEN
            v_errors := v_errors || '["Code explain_bullets: max 2"]'::jsonb;
        END IF;

    ELSE
        -- 'bullets' (default): existing logic
        v_bullets := p_slide_spec->'bullets';
        IF v_bullets IS NULL OR jsonb_typeof(v_bullets) != 'array' THEN
            v_errors := v_errors || '["bullets must be an array"]'::jsonb;
        ELSE
            v_bullet_count := jsonb_array_length(v_bullets);

            IF v_bullet_count < p_min_bullets THEN
                v_errors := v_errors || jsonb_build_array(
                    format('Too few bullets: %s (min: %s)', v_bullet_count, p_min_bullets));
            END IF;

            IF v_bullet_count > p_max_bullets THEN
                v_errors := v_errors || jsonb_build_array(
                    format('Too many bullets: %s (max: %s)', v_bullet_count, p_max_bullets));
            END IF;

            FOR v_i IN 0..v_bullet_count - 1 LOOP
                v_bullet := v_bullets->>v_i;
                IF v_bullet IS NOT NULL THEN
                    v_word_count := array_length(regexp_split_to_array(trim(v_bullet), '\s+'), 1);
                    IF v_word_count > p_max_bullet_words THEN
                        v_errors := v_errors || jsonb_build_array(
                            format('Bullet %s too long: %s words (max: %s)', v_i + 1, v_word_count, p_max_bullet_words));
                    END IF;
                END IF;
            END LOOP;
        END IF;

    END CASE;

    -- Check speaker notes for content slides (not title/thanks)
    IF p_slide_spec->>'intent' IS NOT NULL
       AND p_slide_spec->>'intent' NOT IN ('title', 'thanks') THEN
        IF p_slide_spec->>'speaker_notes' IS NULL
           OR length(trim(p_slide_spec->>'speaker_notes')) < 50 THEN
            v_errors := v_errors || jsonb_build_array(
                'Speaker notes required for content slides (min 50 characters)');
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
