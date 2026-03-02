-- Migration 009: Re-apply fn_validate_slide_structure with max 18 code lines (unchanged)
-- The fix for rag-in-postgres abandonment is in the prompt, not the limit.
-- Kept at 18 lines: the prompt now targets 10-15 lines with explicit structure.

-- No schema change needed; this migration is a no-op since the limit stays at 18.
-- The live DB was temporarily set to 24 during debugging and has been reverted.
SELECT 1;
