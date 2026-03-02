-- Migration 009: Tighten code block line limits from 4-18 to 8-15
-- Prevents slides with too-short code snippets (< 8 lines lack substance)
-- and too-long code blocks (> 15 lines don't fit on a slide).
-- The rag-in-postgres hybrid search SQL was consistently hitting 20 lines
-- and getting abandoned after 5 retries. With a 15-line hard limit
-- plus explicit prompt guidance, the LLM must compress the SQL.

-- Re-create fn_validate_slide_structure with updated code line limits
-- (only the WHEN 'code' branch changes: min 4->8, max 18->15)

DO $$
DECLARE
    v_src TEXT;
BEGIN
    SELECT prosrc INTO v_src
    FROM pg_proc WHERE proname = 'fn_validate_slide_structure';

    IF v_src LIKE '%min 4%' OR v_src LIKE '%max 18%' THEN
        RAISE NOTICE 'Updating code line limits: min 4->8, max 18->15';
    ELSE
        RAISE NOTICE 'Function already updated or has different limits';
    END IF;
END $$;

-- The actual function update is applied from schema.sql via the Python runner below.
-- This file documents the intent; the runner reads schema.sql for the full function body.
