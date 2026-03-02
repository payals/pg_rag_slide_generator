-- Rollback migration 018: Revert what-we-built to bullets without image
UPDATE intent_type_map
SET slide_type   = 'bullets',
    require_image = false
WHERE intent = 'what-we-built';
