-- Rollback for migration 012: Reset html_fragment to NULL for all slide types.
-- This returns to the pre-Phase 8 state where fragments are NULL and the
-- filesystem template (_slide_type_body.html) is used as fallback.

UPDATE slide_type_config SET html_fragment = NULL;
