-- 008_validation_defaults.sql
-- Move bullet validation defaults into intent_type_map so Postgres owns them.

ALTER TABLE intent_type_map
  ADD COLUMN min_bullets INT NOT NULL DEFAULT 2,
  ADD COLUMN max_bullets INT NOT NULL DEFAULT 3,
  ADD COLUMN max_bullet_words INT NOT NULL DEFAULT 15;

-- Types that should have zero bullets (non-bullet slide types)
UPDATE intent_type_map SET min_bullets = 0, max_bullets = 0
  WHERE slide_type IN ('statement', 'split', 'diagram', 'flow');

-- Code slides: 1-2 bullets (for explain_bullets)
UPDATE intent_type_map SET min_bullets = 1, max_bullets = 2
  WHERE slide_type = 'code';
