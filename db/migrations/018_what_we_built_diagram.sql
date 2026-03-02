-- Migration 018: Change what-we-built from bullets to diagram with image
UPDATE intent_type_map
SET slide_type   = 'diagram',
    require_image = true
WHERE intent = 'what-we-built';
