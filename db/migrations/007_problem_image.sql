-- Migration 007: Enable image for problem intent
-- The "problem" slide now requires an image showing fragmented AI infrastructure.

UPDATE intent_type_map
SET require_image = true
WHERE intent = 'problem';
