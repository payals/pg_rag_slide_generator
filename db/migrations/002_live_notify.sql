-- Migration 002: LISTEN/NOTIFY triggers for live deck server
-- 
-- Adds two trigger functions that fire pg_notify events when slides
-- are committed and gate_log rows are written. These events feed the
-- SSE stream in src/server.py for progressive deck rendering.
--
-- Safety: idempotent (uses CREATE OR REPLACE, IF NOT EXISTS)
-- Constraint: pg_notify payload max 8000 bytes; our payloads are ~200 bytes

-- ============================================================================
-- Trigger 1: slide_committed channel
-- ============================================================================
-- Fires AFTER INSERT OR UPDATE on slide table.
-- Inside fn_commit_slide, the slide INSERT and all gate_log INSERTs happen
-- in one transaction. All NOTIFYs fire at COMMIT time simultaneously.
-- The server uses a separate progress queue for real-time phase updates.

CREATE OR REPLACE FUNCTION notify_slide_committed() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('slide_committed', json_build_object(
        'deck_id', NEW.deck_id::text,
        'slide_no', NEW.slide_no,
        'intent', NEW.intent::text,
        'title', NEW.title
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY INVOKER SET search_path = public;

-- Use IF NOT EXISTS pattern for idempotent migration
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_slide_committed') THEN
        CREATE TRIGGER trg_slide_committed
            AFTER INSERT OR UPDATE ON slide
            FOR EACH ROW EXECUTE FUNCTION notify_slide_committed();
    END IF;
END $$;

-- ============================================================================
-- Trigger 2: gate_update channel
-- ============================================================================
-- Note: pg_notify payload limit is 8000 bytes. Keep payloads small.
-- Never put slide content (bullets, notes) in the NOTIFY payload.
-- gate_log.deck_id is nullable -- use COALESCE.

CREATE OR REPLACE FUNCTION notify_gate_update() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('gate_update', json_build_object(
        'deck_id', COALESCE(NEW.deck_id::text, ''),
        'slide_no', NEW.slide_no,
        'gate_name', NEW.gate_name,
        'decision', NEW.decision::text,
        'score', COALESCE(NEW.score, 0)
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY INVOKER SET search_path = public;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_gate_update') THEN
        CREATE TRIGGER trg_gate_update
            AFTER INSERT ON gate_log
            FOR EACH ROW EXECUTE FUNCTION notify_gate_update();
    END IF;
END $$;
