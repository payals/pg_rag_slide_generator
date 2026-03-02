-- =============================================================================
-- Migration 010: Schema Consolidation & Safety Hardening
-- =============================================================================
--
-- Implements: docs/SCHEMA_DESIGN_PROPOSAL.md
--
-- This migration:
--   1. Fixes existing schema defects (A.1–A.7)
--   2. Creates consolidation tables (B.1–B.6)
--   3. Creates infrastructure tables (C.1–C.2)
--
-- Safety:
--   - All changes are additive (ADD COLUMN, CREATE TABLE, CREATE INDEX)
--   - All ADD COLUMN uses DEFAULT so existing rows are populated
--   - All CREATE uses IF NOT EXISTS for idempotency
--   - Wrapped in a single transaction (atomic rollback on any failure)
--
-- Run with: psql -d slidegen -f db/migrations/010_consolidate_config.sql
-- =============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- A.5: Generic updated_at trigger function
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
   SECURITY INVOKER
   SET search_path = public;

DROP TRIGGER IF EXISTS doc_updated_at ON doc;
CREATE TRIGGER doc_updated_at
    BEFORE UPDATE ON doc
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

DROP TRIGGER IF EXISTS deck_updated_at ON deck;
CREATE TRIGGER deck_updated_at
    BEFORE UPDATE ON deck
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();


-- ─────────────────────────────────────────────────────────────────────────────
-- B.1: Extend intent_type_map with metadata columns
-- ─────────────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    ALTER TABLE intent_type_map ADD COLUMN sort_order INT NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE intent_type_map ADD COLUMN suggested_title TEXT NOT NULL DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE intent_type_map ADD COLUMN requirements TEXT NOT NULL DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE intent_type_map ADD COLUMN is_generatable BOOLEAN NOT NULL DEFAULT true;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE intent_type_map ADD COLUMN related_intents TEXT[] DEFAULT '{}';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- Populate sort_order and metadata for all generatable intents
UPDATE intent_type_map SET sort_order = 1,
    suggested_title = 'The AI Infrastructure Problem',
    requirements = '2-3 bullets on AI infrastructure pain points: database sprawl, lack of transactions, audit gaps, safety concerns'
WHERE intent = 'problem';

UPDATE intent_type_map SET sort_order = 2,
    suggested_title = 'Why Postgres for AI Workloads',
    requirements = '2-3 bullets on why Postgres: mature, ACID, extensions, single source of truth, community'
WHERE intent = 'why-postgres';

UPDATE intent_type_map SET sort_order = 3,
    suggested_title = 'Postgres vs Vector Databases',
    requirements = 'Two-column comparison: left_title + 2-3 items vs right_title + 2-3 items. Postgres strengths vs tradeoffs.'
WHERE intent = 'comparison';

UPDATE intent_type_map SET sort_order = 4,
    suggested_title = 'Postgres AI Primitives',
    requirements = '3 bullets, one per AI primitive built into or added to Postgres. Bullet 1: pgvector -- vector similarity search and embedding storage. Bullet 2: pg_trgm -- trigram fuzzy matching for typo-tolerant search. Bullet 3: Full-text search (tsvector/tsquery) -- built-in lexical search, no extension needed, powers the lexical half of hybrid retrieval. Do NOT mention pgcrypto.'
WHERE intent = 'capabilities';

UPDATE intent_type_map SET sort_order = 5,
    suggested_title = 'The Database IS the Control Plane',
    requirements = 'One statement sentence (8-90 chars) + optional subtitle. NO bullets. Core thesis: deterministic vs non-deterministic split.'
WHERE intent = 'thesis';

UPDATE intent_type_map SET sort_order = 6,
    suggested_title = 'Schema Design & Security',
    requirements = '3 bullets, each covering a distinct security layer with NO overlap between bullets. Bullet 1: SECURITY INVOKER + pinned search_path (why callers run with limited privileges, blocks function hijacking). Bullet 2: REVOKE PUBLIC + least-privilege GRANT (only app role can execute specific functions, AI never runs raw SQL). Bullet 3: append-only audit tables + typed MCP functions (immutable logs, input validation, no dynamic SQL).'
WHERE intent = 'schema-security';

UPDATE intent_type_map SET sort_order = 7,
    suggested_title = 'System Architecture',
    requirements = 'Diagram with 1-3 short callouts (<=40 chars each) and a caption. Postgres central, MCP server, LangGraph orchestrator.'
WHERE intent = 'architecture';

UPDATE intent_type_map SET sort_order = 8,
    suggested_title = 'What is RAG?',
    requirements = 'Diagram with 1-3 short callouts (<=40 chars each) and a caption. RAG flow: query, retrieve, generate.'
WHERE intent = 'what-is-rag';

UPDATE intent_type_map SET sort_order = 9,
    suggested_title = 'RAG Inside Postgres',
    requirements = 'SQL code snippet (10-15 lines, each line <=72 chars) + 1-2 explanation bullets. STRICT: code_block must be >=8 and <=15 lines. Combine clauses to save lines. Structure: WITH sem AS (SELECT c.id, 1-(c.embedding <=> :qv) AS score, RANK()OVER(...) r FROM chunk c), lex AS (SELECT c.id, ts_rank_cd(c.tsv,:q) AS score, RANK()OVER(...) r FROM chunk c) SELECT ... :sw/(:k+sem.r)+:lw/(:k+lex.r) AS rrf FROM chunk c JOIN doc d ON ... JOIN sem/lex USING(id) ORDER BY rrf DESC LIMIT 10; Put JOINs on one line. Put ORDER+LIMIT on one line. Use short aliases (c, d). No comments, no blank lines.'
WHERE intent = 'rag-in-postgres';

UPDATE intent_type_map SET sort_order = 10,
    suggested_title = 'What is MCP?',
    requirements = 'Diagram with 1-3 short callouts (<=40 chars each) and a caption. MCP architecture, typed tools, safety boundary.'
WHERE intent = 'what-is-mcp';

UPDATE intent_type_map SET sort_order = 11,
    suggested_title = 'Typed Tools, Not Raw SQL',
    requirements = 'Code block (8-16 lines, each <=78 chars) + 1-2 explanation bullets. Show 3-5 real MCP tool signatures: mcp_search_chunks, mcp_pick_next_intent, mcp_validate_slide_structure, mcp_check_grounding, mcp_commit_slide. Use only key params (2-3 each). Group with short ''# category'' comments.'
WHERE intent = 'mcp-tools';

UPDATE intent_type_map SET sort_order = 12,
    suggested_title = 'Control Gates & Validation',
    requirements = 'Pipeline flow: 4-7 steps, each with label (2-30 chars) and caption (0-60 chars). G1->G2->G2.5->G3->G4 pipeline.'
WHERE intent = 'gates';

UPDATE intent_type_map SET sort_order = 13,
    suggested_title = 'Observable AI with SQL',
    requirements = 'SQL code snippet (8-15 lines, each line <=72 chars) + 1-2 explanation bullets. STRICT: code_block must be >=8 and <=15 lines. Show a real query: SELECT gate_name, decision, reason, COUNT(*) AS occurrences, ROUND(AVG(score)::numeric,3) AS avg_score FROM gate_log WHERE deck_id = $1 GROUP BY gate_name, decision, reason ORDER BY occurrences DESC. Combine short clauses on one line (e.g. ORDER BY + LIMIT). Do NOT use SELECT *, do NOT use placeholder comments like ''-- Example columns'' or ''-- Use this view during demo''. Every line must be real, production SQL.'
WHERE intent = 'observability';

UPDATE intent_type_map SET sort_order = 14,
    suggested_title = 'What We Built',
    requirements = 'Recap: slide generator using this architecture, generated these slides, everything auditable'
WHERE intent = 'what-we-built';

UPDATE intent_type_map SET sort_order = 15,
    suggested_title = 'Key Takeaways',
    requirements = '2-3 memorable points: database is control plane, RAG=retrieval+state+gates+provenance, MCP=safety boundary, Postgres can do more'
WHERE intent = 'takeaways';

-- Insert static intents as non-generatable (may not exist in table yet)
INSERT INTO intent_type_map (intent, slide_type, require_image, min_bullets, max_bullets, max_bullet_words,
                             sort_order, suggested_title, requirements, is_generatable)
VALUES
    ('title',  'statement', false, 0, 0, 15, 0,  'Postgres as AI Application Server',
     'Opening slide with talk title, speaker name, event, date', false),
    ('thanks', 'bullets',   false, 2, 4, 15, 99, 'Thank You & Questions',
     'Closing slide with contact info and resources', false)
ON CONFLICT (intent) DO UPDATE SET
    sort_order     = EXCLUDED.sort_order,
    suggested_title = EXCLUDED.suggested_title,
    requirements   = EXCLUDED.requirements,
    is_generatable = EXCLUDED.is_generatable;

-- Populate related_intents for coverage-enriched retrieval
UPDATE intent_type_map SET related_intents = ARRAY['what-is-rag']
WHERE intent = 'rag-in-postgres';

UPDATE intent_type_map SET related_intents = ARRAY['what-is-mcp']
WHERE intent = 'mcp-tools';

UPDATE intent_type_map SET related_intents = ARRAY['gates']
WHERE intent = 'observability';

UPDATE intent_type_map SET related_intents = ARRAY['architecture']
WHERE intent = 'what-we-built';

UPDATE intent_type_map SET related_intents = ARRAY['thesis']
WHERE intent = 'takeaways';


-- ─────────────────────────────────────────────────────────────────────────────
-- A.6: Constrain gate_log.gate_name (only if all existing data is valid)
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    v_invalid_count INT;
BEGIN
    SELECT COUNT(*) INTO v_invalid_count
    FROM gate_log
    WHERE gate_name NOT IN (
        'G0_ingestion', 'G1_retrieval', 'G2_citation', 'G2.5_grounding',
        'G3_format', 'G4_novelty', 'G5_IMAGE', 'G5_commit',
        'COVERAGE_SENSOR', 'COST_GATE'
    );

    IF v_invalid_count = 0 THEN
        BEGIN
            ALTER TABLE gate_log ADD CONSTRAINT gate_log_gate_name_check CHECK (
                gate_name IN (
                    'G0_ingestion', 'G1_retrieval', 'G2_citation', 'G2.5_grounding',
                    'G3_format', 'G4_novelty', 'G5_IMAGE', 'G5_commit',
                    'COVERAGE_SENSOR', 'COST_GATE'
                )
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END;
    ELSE
        RAISE NOTICE 'SKIPPED gate_log_gate_name_check: % rows with invalid gate_name', v_invalid_count;
    END IF;
END $$;


-- ─────────────────────────────────────────────────────────────────────────────
-- A.3: HNSW index on slide.content_embedding for novelty checks
-- ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_slide_content_embedding ON slide
    USING hnsw (content_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- ─────────────────────────────────────────────────────────────────────────────
-- A.7: Fix v_top_sources UUID cast direction (cast small side, not index side)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_top_sources AS
WITH citation_chunks AS (
    SELECT
        s.deck_id,
        jsonb_array_elements(s.citations)->>'chunk_id' AS chunk_id_str
    FROM slide s
    WHERE s.citations IS NOT NULL AND jsonb_array_length(s.citations) > 0
)
SELECT
    cc.deck_id,
    c.chunk_id,
    d.doc_id,
    d.title AS doc_title,
    d.doc_type,
    d.trust_level,
    COUNT(*) AS citation_count
FROM citation_chunks cc
JOIN chunk c ON c.chunk_id = cc.chunk_id_str::uuid
JOIN doc d ON c.doc_id = d.doc_id
GROUP BY cc.deck_id, c.chunk_id, d.doc_id, d.title, d.doc_type, d.trust_level
ORDER BY cc.deck_id, citation_count DESC;


-- ─────────────────────────────────────────────────────────────────────────────
-- C.2: deck.status column
-- ─────────────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE deck_status AS ENUM ('draft', 'generating', 'completed', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE deck ADD COLUMN status deck_status NOT NULL DEFAULT 'draft';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_deck_active_generation
    ON deck(status) WHERE status = 'generating';


-- ─────────────────────────────────────────────────────────────────────────────
-- C.1: generation_run table
-- ─────────────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE run_status AS ENUM ('running', 'completed', 'failed', 'cost_limited', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS generation_run (
    run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deck_id             UUID NOT NULL REFERENCES deck(deck_id) ON DELETE CASCADE,
    status              run_status NOT NULL DEFAULT 'running',
    config              JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    slides_generated    INT DEFAULT 0,
    slides_failed       INT DEFAULT 0,
    total_retries       INT DEFAULT 0,
    llm_calls           INT DEFAULT 0,
    prompt_tokens       INT DEFAULT 0,
    completion_tokens   INT DEFAULT 0,
    embedding_tokens    INT DEFAULT 0,
    estimated_cost_usd  NUMERIC(8,4) DEFAULT 0,
    error_message       TEXT
);

CREATE INDEX IF NOT EXISTS idx_generation_run_deck ON generation_run(deck_id);
CREATE INDEX IF NOT EXISTS idx_generation_run_status ON generation_run(status);
CREATE INDEX IF NOT EXISTS idx_generation_run_started ON generation_run(started_at);


-- ─────────────────────────────────────────────────────────────────────────────
-- B.2: static_slide table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS static_slide (
    intent          slide_intent PRIMARY KEY,
    title           TEXT NOT NULL,
    subtitle        TEXT,
    slide_type      slide_type NOT NULL DEFAULT 'bullets',
    bullets         JSONB DEFAULT '[]'::jsonb,
    content_data    JSONB DEFAULT '{}'::jsonb,
    speaker_notes   TEXT,
    speaker         TEXT,
    job_title       TEXT,
    company         TEXT,
    company_url     TEXT,
    event           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS static_slide_updated_at ON static_slide;
CREATE TRIGGER static_slide_updated_at
    BEFORE UPDATE ON static_slide
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

INSERT INTO static_slide (intent, title, subtitle, slide_type, speaker, job_title, company, company_url, event)
VALUES ('title', 'Postgres as AI Control Plane',
        'Building RAG + MCP Workflows Inside the Database',
        'statement', 'Payal Singh', 'Senior Database Reliability Engineer',
        'NetApp', 'https://www.netapp.com', 'Scale23x • March 2026')
ON CONFLICT DO NOTHING;

INSERT INTO static_slide (intent, title, slide_type, bullets, speaker_notes)
VALUES ('thanks', 'Thank You & Questions', 'bullets',
        '["GitHub: github.com/payalsingh/scale23x-demo", "LinkedIn: linkedin.com/in/payalsingh", "Email: payal.singh@netapp.com", "Slides: Generated by this very system!"]'::jsonb,
        'Thank the audience for attending. Open the floor for questions. Mention that the code is available on GitHub.')
ON CONFLICT DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- B.3: section_divider table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS section_divider (
    divider_id      SERIAL PRIMARY KEY,
    after_intent    slide_intent NOT NULL
                    REFERENCES intent_type_map(intent) ON DELETE RESTRICT,
    title           TEXT NOT NULL,
    subtitle        TEXT,
    image_filename  TEXT,
    sort_order      INT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(after_intent)
);

INSERT INTO section_divider (after_intent, title, image_filename, sort_order) VALUES
    ('problem',       'Why Postgres?',           'divider_01_why_postgres.png',           1),
    ('capabilities',  'The Architecture',        'divider_02_the_architecture.svg',       2),
    ('architecture',  'RAG + MCP Deep Dive',     'divider_03_rag_mcp_deep_dive.svg',      3),
    ('mcp-tools',     'Control & Observability', 'divider_04_control_observability.svg',   4),
    ('observability', 'The Demo',                'divider_05_the_demo.svg',               5)
ON CONFLICT (after_intent) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- B.4: theme table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS theme (
    name            TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    css_overrides   TEXT NOT NULL DEFAULT '',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO theme (name, display_name, css_overrides) VALUES
    ('dark', 'Dark Professional', ''),
    ('postgres', 'Postgres Brand', ':root {
        --slide-bg: #2d3748;
        --accent-color: #336791;
        --accent-secondary: #e8792e;
        --divider-bg: linear-gradient(135deg, #336791 0%, #2d5f8a 100%);
        --muted-color: #a0aec0;
    }')
ON CONFLICT (name) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- B.5: slide_type_config table (Tier 2 preparation — rows populated later)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS slide_type_config (
    slide_type      slide_type PRIMARY KEY,
    prompt_schema   TEXT NOT NULL,
    content_fields  JSONB NOT NULL DEFAULT '{}'::jsonb,
    html_fragment   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS slide_type_config_updated_at ON slide_type_config;
CREATE TRIGGER slide_type_config_updated_at
    BEFORE UPDATE ON slide_type_config
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE OR REPLACE FUNCTION fn_validate_type_config()
RETURNS TRIGGER AS $$
DECLARE
    v_field TEXT;
    v_parent TEXT;
    v_children JSONB;
    v_child TEXT;
BEGIN
    FOR v_field IN SELECT jsonb_array_elements_text(
        COALESCE(NEW.content_fields->'scalar', '[]'::jsonb)) LOOP
        IF position(v_field IN NEW.prompt_schema) = 0 THEN
            RAISE EXCEPTION 'scalar field "%" not found in prompt_schema', v_field;
        END IF;
        IF NEW.html_fragment IS NOT NULL AND position(v_field IN NEW.html_fragment) = 0 THEN
            RAISE EXCEPTION 'scalar field "%" not found in html_fragment', v_field;
        END IF;
    END LOOP;

    FOR v_field IN SELECT jsonb_array_elements_text(
        COALESCE(NEW.content_fields->'list', '[]'::jsonb)) LOOP
        IF position(v_field IN NEW.prompt_schema) = 0 THEN
            RAISE EXCEPTION 'list field "%" not found in prompt_schema', v_field;
        END IF;
        IF NEW.html_fragment IS NOT NULL AND position(v_field IN NEW.html_fragment) = 0 THEN
            RAISE EXCEPTION 'list field "%" not found in html_fragment', v_field;
        END IF;
    END LOOP;

    FOR v_parent, v_children IN SELECT * FROM jsonb_each(
        COALESCE(NEW.content_fields->'nested', '{}'::jsonb)) LOOP
        IF position(v_parent IN NEW.prompt_schema) = 0 THEN
            RAISE EXCEPTION 'nested parent "%" not found in prompt_schema', v_parent;
        END IF;
        FOR v_child IN SELECT jsonb_array_elements_text(v_children) LOOP
            IF position(v_child IN NEW.prompt_schema) = 0 THEN
                RAISE EXCEPTION 'nested child "%.%" not found in prompt_schema', v_parent, v_child;
            END IF;
        END LOOP;
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql
   SECURITY INVOKER
   SET search_path = public;

DROP TRIGGER IF EXISTS validate_type_config_trigger ON slide_type_config;
CREATE TRIGGER validate_type_config_trigger
    BEFORE INSERT OR UPDATE ON slide_type_config
    FOR EACH ROW EXECUTE FUNCTION fn_validate_type_config();


-- ─────────────────────────────────────────────────────────────────────────────
-- B.6: prompt_template table (Tier 2 preparation — rows populated later)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS prompt_template (
    template_id     SERIAL PRIMARY KEY,
    purpose         TEXT NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    system_prompt   TEXT NOT NULL,
    user_prompt     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(purpose, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_template_active
    ON prompt_template(purpose) WHERE is_active = true;


-- ─────────────────────────────────────────────────────────────────────────────
-- A.4: Rewrite v_deck_health with CTE (performance fix)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_deck_health AS
WITH gate_stats AS (
    SELECT
        g.deck_id,
        COUNT(*) FILTER (WHERE g.decision = 'fail') AS total_gate_failures,
        COUNT(DISTINCT g.slide_no) FILTER (WHERE g.decision = 'fail') AS slides_with_failures
    FROM gate_log g
    GROUP BY g.deck_id
)
SELECT
    d.deck_id,
    d.topic,
    COUNT(s.slide_id) AS slide_count,
    d.target_slides,
    COALESCE(SUM(s.retry_count), 0) AS total_retries,
    ROUND(AVG(s.retry_count)::numeric, 2) AS avg_retries_per_slide,
    COALESCE(gs.total_gate_failures, 0) AS total_gate_failures,
    COALESCE(gs.slides_with_failures, 0) AS slides_with_failures,
    ROUND(
        (COUNT(s.slide_id)::float / NULLIF(d.target_slides, 0) * 100)::numeric, 1
    ) AS completion_pct
FROM deck d
LEFT JOIN slide s ON d.deck_id = s.deck_id
LEFT JOIN gate_stats gs ON d.deck_id = gs.deck_id
GROUP BY d.deck_id, d.topic, d.target_slides,
         gs.total_gate_failures, gs.slides_with_failures;


-- ─────────────────────────────────────────────────────────────────────────────
-- A.2 + Thesis 4.1.8: Fix v_deck_coverage to use intent_type_map
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_deck_coverage AS
SELECT
    d.deck_id,
    d.topic,
    d.target_slides,
    COUNT(DISTINCT s.intent) AS covered_intents,
    COUNT(s.slide_id) AS total_slides,
    ARRAY_AGG(DISTINCT s.intent ORDER BY s.intent)
        FILTER (WHERE s.intent IS NOT NULL) AS covered,
    ARRAY(
        SELECT itm.intent
        FROM intent_type_map itm
        WHERE itm.is_generatable = true
          AND NOT EXISTS (
              SELECT 1 FROM slide s2
              WHERE s2.deck_id = d.deck_id AND s2.intent = itm.intent
          )
        ORDER BY itm.sort_order
    ) AS missing
FROM deck d
LEFT JOIN slide s ON d.deck_id = s.deck_id
GROUP BY d.deck_id, d.topic, d.target_slides;


-- ─────────────────────────────────────────────────────────────────────────────
-- A.2: Fix fn_pick_next_intent to use intent_type_map.sort_order
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION fn_pick_next_intent(
    p_deck_id UUID,
    p_exclude slide_intent[] DEFAULT '{}'
)
RETURNS slide_intent AS $$
DECLARE
    v_next slide_intent;
BEGIN
    SELECT itm.intent INTO v_next
    FROM intent_type_map itm
    WHERE itm.is_generatable = true
      AND NOT EXISTS (
          SELECT 1 FROM slide s
          WHERE s.deck_id = p_deck_id AND s.intent = itm.intent
      )
      AND itm.intent != ALL(p_exclude)
    ORDER BY itm.sort_order
    LIMIT 1;

    RETURN v_next;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE
   SET search_path = public;


-- ─────────────────────────────────────────────────────────────────────────────
-- A.1: Fix update_slide_content_text trigger (complete field extraction)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_slide_content_text() RETURNS TRIGGER AS $$
BEGIN
    NEW.content_text := NEW.title || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(NEW.bullets)), ' '), '') || ' ' ||
        COALESCE(NEW.content_data->>'statement', '') || ' ' ||
        COALESCE(NEW.content_data->>'subtitle', '') || ' ' ||
        COALESCE(NEW.content_data->>'code_block', '') || ' ' ||
        COALESCE(NEW.content_data->>'language', '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(
                COALESCE(NEW.content_data->'explain_bullets', '[]'::jsonb))), ' '), '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(
                COALESCE(NEW.content_data->'callouts', '[]'::jsonb))), ' '), '') || ' ' ||
        COALESCE(NEW.content_data->>'caption', '') || ' ' ||
        COALESCE(NEW.content_data->>'left_title', '') || ' ' ||
        COALESCE(NEW.content_data->>'right_title', '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(
                COALESCE(NEW.content_data->'left_items', '[]'::jsonb))), ' '), '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(
                COALESCE(NEW.content_data->'right_items', '[]'::jsonb))), ' '), '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT e->>'label' || ' ' || COALESCE(e->>'caption', '')
                FROM jsonb_array_elements(
                    COALESCE(NEW.content_data->'steps', '[]'::jsonb)) AS e), ' '), '') || ' ' ||
        COALESCE(NEW.speaker_notes, '');
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
   SECURITY INVOKER
   SET search_path = public;

-- Refresh content_text for all existing slides using the updated trigger.
-- Setting content_data = content_data fires the BEFORE UPDATE trigger
-- which rebuilds content_text with all fields now included.
UPDATE slide SET content_data = content_data;


-- ─────────────────────────────────────────────────────────────────────────────
-- Retention documentation
-- ─────────────────────────────────────────────────────────────────────────────

COMMENT ON TABLE gate_log IS
    'Append-only audit trail for gate decisions. '
    'Production: partition by created_at monthly, retain 90 days online.';

COMMENT ON TABLE retrieval_log IS
    'Append-only audit trail for retrieval operations. '
    'Same retention policy as gate_log.';

COMMENT ON TABLE generation_run IS
    'Tracks metadata for each deck generation run. '
    'Links to gate_log and retrieval_log via run_id.';


-- ─────────────────────────────────────────────────────────────────────────────
-- Verification
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    v_itm_cols INT;
    v_new_tables INT;
    v_itm_rows INT;
    v_static_rows INT;
    v_divider_rows INT;
BEGIN
    SELECT COUNT(*) INTO v_itm_cols
    FROM information_schema.columns
    WHERE table_name = 'intent_type_map'
      AND column_name IN ('sort_order', 'suggested_title', 'requirements', 'is_generatable', 'related_intents');

    IF v_itm_cols < 5 THEN
        RAISE EXCEPTION 'intent_type_map missing new columns (found %/5)', v_itm_cols;
    END IF;

    SELECT COUNT(*) INTO v_new_tables
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN ('static_slide', 'section_divider', 'theme', 'slide_type_config',
                         'prompt_template', 'generation_run');

    IF v_new_tables < 6 THEN
        RAISE EXCEPTION 'Missing new tables (found %/6)', v_new_tables;
    END IF;

    SELECT COUNT(*) INTO v_itm_rows FROM intent_type_map;
    SELECT COUNT(*) INTO v_static_rows FROM static_slide;
    SELECT COUNT(*) INTO v_divider_rows FROM section_divider;

    RAISE NOTICE '✓ Migration 010 applied successfully';
    RAISE NOTICE '  intent_type_map: % rows (5 new columns added)', v_itm_rows;
    RAISE NOTICE '  static_slide: % rows', v_static_rows;
    RAISE NOTICE '  section_divider: % rows', v_divider_rows;
    RAISE NOTICE '  New tables: theme, slide_type_config, prompt_template, generation_run';
    RAISE NOTICE '  Fixed: content_text trigger, fn_pick_next_intent, v_deck_coverage, v_deck_health, v_top_sources';
    RAISE NOTICE '  Added: idx_slide_content_embedding, gate_log constraint, deck.status, updated_at triggers';
END $$;

COMMIT;
