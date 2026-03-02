-- Migration 019: Change takeaways intent from bullets to split (bullets + image)
-- Rationale: Key Takeaways slide benefits from a consolidation diagram alongside bullet points

UPDATE intent_type_map
SET slide_type   = 'split',
    require_image = TRUE
WHERE intent = 'takeaways';
