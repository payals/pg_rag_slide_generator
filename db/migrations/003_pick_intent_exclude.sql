-- Migration 003: Add p_exclude parameter to fn_pick_next_intent
-- Fixes infinite loop when abandoned intents keep being returned by the DB.
--
-- Before: fn_pick_next_intent(p_deck_id UUID) returns the first uncovered intent,
--         even if the orchestrator has already abandoned it (retry exhaustion).
-- After:  fn_pick_next_intent(p_deck_id UUID, p_exclude slide_intent[]) skips
--         excluded intents (e.g. abandoned) at the SQL level.

-- Step 1: Drop old 1-param overload (if it exists)
DROP FUNCTION IF EXISTS fn_pick_next_intent(uuid);

-- Step 2: Create/replace the 2-param version with default
CREATE OR REPLACE FUNCTION fn_pick_next_intent(
    p_deck_id UUID,
    p_exclude  slide_intent[] DEFAULT '{}'
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
