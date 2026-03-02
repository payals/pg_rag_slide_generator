-- =============================================================================
-- Postgres-First AI Slide Generator Schema
-- Scale23x Demo: "Postgres as an AI Application Server"
-- =============================================================================
--
-- This schema implements the complete database layer for RAG + MCP workflows.
-- All deterministic logic lives here. The LLM only drafts; Postgres controls.
--
-- Run with: psql -d slidegen -f schema.sql
--
-- =============================================================================
-- SECURITY & STANDARDS NOTES
-- =============================================================================
--
-- 1. SECURITY INVOKER: All functions run with caller's permissions (not elevated)
-- 2. SET search_path: All functions explicitly set search_path to prevent hijacking
-- 3. PARALLEL SAFE/UNSAFE: Declared for query planner optimization
-- 4. No dynamic SQL: All queries use parameterized plpgsql, no SQL injection risk
-- 5. REVOKE PUBLIC: Production should revoke default public execute on functions
--
-- Normalization: Intentional denormalization for bullets/citations as JSONB arrays
-- (acceptable trade-off: small arrays, rarely queried individually, simpler API)
--
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. EXTENSIONS
-- -----------------------------------------------------------------------------
-- Enable required extensions (run as superuser or with appropriate permissions)

CREATE EXTENSION IF NOT EXISTS vector;           -- pgvector: semantic similarity
CREATE EXTENSION IF NOT EXISTS pg_trgm;          -- Trigram: lexical similarity
CREATE EXTENSION IF NOT EXISTS pgcrypto;         -- Hashing, UUID generation
CREATE EXTENSION IF NOT EXISTS unaccent;         -- Full-text normalization
-- Note: pg_stat_statements requires shared_preload_libraries config change
-- CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- -----------------------------------------------------------------------------
-- 2. CUSTOM TYPES
-- -----------------------------------------------------------------------------

-- Document types for the knowledge base
CREATE TYPE doc_type AS ENUM ('note', 'article', 'concept', 'blog', 'external', 'image');

-- Image style categories
CREATE TYPE image_style AS ENUM ('diagram', 'screenshot', 'chart', 'photo', 'decorative');

-- Trust levels for sources (affects retrieval ranking)
CREATE TYPE trust_level AS ENUM ('low', 'medium', 'high');

-- Gate decision outcomes
CREATE TYPE gate_decision AS ENUM ('pass', 'fail');

-- Slide intents (the purpose of each slide)
CREATE TYPE slide_intent AS ENUM (
    'title',           -- Static: opening slide
    'problem',
    'why-postgres',
    'comparison',
    'capabilities',
    'thesis',
    'schema-security',
    'architecture',
    'what-is-rag',
    'rag-in-postgres',
    'advanced-retrieval',
    'what-is-mcp',
    'mcp-tools',
    'gates',
    'observability',
    'what-we-built',
    'takeaways',
    'thanks'           -- Static: closing slide
);

-- Slide layout types
CREATE TYPE slide_type AS ENUM (
    'statement', 'bullets', 'split', 'flow', 'diagram', 'code'
);

-- -----------------------------------------------------------------------------
-- 3. TABLES
-- -----------------------------------------------------------------------------

-- doc: Source documents in the knowledge base
CREATE TABLE doc (
    doc_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_type        doc_type NOT NULL,
    title           TEXT NOT NULL,
    source_path     TEXT,                        -- Local path or URL
    source_url      TEXT,                        -- Original URL if external
    trust_level     trust_level NOT NULL DEFAULT 'medium',
    tags            TEXT[] DEFAULT '{}',
    content_hash    TEXT,                        -- Hash of raw content for change detection
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_doc_type ON doc(doc_type);
CREATE INDEX idx_doc_trust ON doc(trust_level);
CREATE INDEX idx_doc_tags ON doc USING GIN(tags);

-- chunk: Text chunks with embeddings and full-text search vectors
CREATE TABLE chunk (
    chunk_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES doc(doc_id) ON DELETE CASCADE,
    chunk_index     INT NOT NULL,                -- Position within document
    content         TEXT NOT NULL,
    content_hash    TEXT NOT NULL,               -- For deduplication
    tsv             TSVECTOR,                    -- Full-text search vector
    embedding       VECTOR(1536),                -- OpenAI text-embedding-3-small
    embedding_model TEXT DEFAULT 'text-embedding-3-small',
    token_count     INT,
    overlap_tokens  INT DEFAULT 0,               -- Tokens overlapping with previous chunk
    section_header  TEXT,                        -- Preserved section header for context
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    CONSTRAINT chunk_doc_index_unique UNIQUE(doc_id, chunk_index)
);

-- Vector index for semantic search (HNSW for better recall)
CREATE INDEX idx_chunk_embedding ON chunk 
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- GIN index for full-text search
CREATE INDEX idx_chunk_tsv ON chunk USING GIN(tsv);

-- Index for deduplication lookups
CREATE INDEX idx_chunk_content_hash ON chunk(content_hash);

-- Composite index for document-based queries
CREATE INDEX idx_chunk_doc ON chunk(doc_id, chunk_index);

-- Trigger to auto-update tsvector
CREATE OR REPLACE FUNCTION update_chunk_tsv() RETURNS TRIGGER AS $$
BEGIN
    NEW.tsv := to_tsvector('english', unaccent(NEW.content));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
   SECURITY INVOKER
   SET search_path = public;

CREATE TRIGGER chunk_tsv_update
    BEFORE INSERT OR UPDATE OF content ON chunk
    FOR EACH ROW EXECUTE FUNCTION update_chunk_tsv();

-- deck: Presentation metadata and configuration
CREATE TABLE deck (
    deck_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic           TEXT NOT NULL,
    description     TEXT,
    style_contract  JSONB DEFAULT '{}'::jsonb,   -- Tone, glossary, constraints
    target_slides   INT NOT NULL DEFAULT 14,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    CONSTRAINT deck_target_positive CHECK (target_slides > 0)
);

-- slide: Individual slides with content, citations, and metadata
CREATE TABLE slide (
    slide_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deck_id             UUID NOT NULL REFERENCES deck(deck_id) ON DELETE CASCADE,
    slide_no            INT NOT NULL,
    intent              slide_intent NOT NULL,
    title               TEXT NOT NULL,
    slide_type          slide_type NOT NULL DEFAULT 'bullets',
    bullets             JSONB NOT NULL DEFAULT '[]'::jsonb,  -- Array of bullet strings
    content_data        JSONB DEFAULT '{}'::jsonb,           -- Type-specific structured content
    speaker_notes       TEXT,
    citations           JSONB DEFAULT '[]'::jsonb,           -- Array of {chunk_id, title, url}
    content_text        TEXT,                                -- Concatenated: title + bullets + notes
    content_embedding   VECTOR(1536),                        -- For novelty checks
    retry_count         INT DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    CONSTRAINT slide_deck_no_unique UNIQUE(deck_id, slide_no),
    CONSTRAINT slide_no_positive CHECK (slide_no > 0)
);

CREATE INDEX idx_slide_deck ON slide(deck_id);
CREATE INDEX idx_slide_intent ON slide(intent);

-- Trigger to auto-generate content_text for novelty comparisons
CREATE OR REPLACE FUNCTION update_slide_content_text() RETURNS TRIGGER AS $$
BEGIN
    NEW.content_text := NEW.title || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(NEW.bullets)), ' '), '') || ' ' ||
        COALESCE(NEW.content_data->>'statement', '') || ' ' ||
        COALESCE(NEW.content_data->>'subtitle', '') || ' ' ||
        COALESCE(NEW.content_data->>'code_block', '') || ' ' ||
        COALESCE(NEW.content_data->>'caption', '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(
                COALESCE(NEW.content_data->'left_items', '[]'::jsonb))), ' '), '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(
                COALESCE(NEW.content_data->'right_items', '[]'::jsonb))), ' '), '') || ' ' ||
        COALESCE(array_to_string(
            ARRAY(SELECT e->>'label' FROM jsonb_array_elements(
                COALESCE(NEW.content_data->'steps', '[]'::jsonb)) AS e), ' '), '') || ' ' ||
        COALESCE(NEW.speaker_notes, '');
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
   SECURITY INVOKER
   SET search_path = public;

CREATE TRIGGER slide_content_text_update
    BEFORE INSERT OR UPDATE OF title, bullets, speaker_notes, content_data ON slide
    FOR EACH ROW EXECUTE FUNCTION update_slide_content_text();

-- intent_type_map: DB-owned mapping of intent to slide type (control plane)
CREATE TABLE intent_type_map (
    intent           slide_intent PRIMARY KEY,
    slide_type       slide_type NOT NULL,
    require_image    BOOLEAN NOT NULL DEFAULT false,
    min_bullets      INT NOT NULL DEFAULT 2,
    max_bullets      INT NOT NULL DEFAULT 3,
    max_bullet_words INT NOT NULL DEFAULT 15
);

INSERT INTO intent_type_map (intent, slide_type, require_image, min_bullets, max_bullets) VALUES
    ('problem',         'bullets',   false, 2, 3),
    ('why-postgres',    'bullets',   false, 2, 3),
    ('comparison',      'split',     false, 0, 0),
    ('capabilities',    'bullets',   false, 2, 3),
    ('thesis',          'statement', false, 0, 0),
    ('schema-security', 'bullets',   false, 2, 3),
    ('architecture',    'diagram',   true,  0, 0),
    ('what-is-rag',     'diagram',   true,  0, 0),
    ('rag-in-postgres',     'code',      false, 1, 2),
    ('advanced-retrieval',  'split',     false, 0, 0),
    ('what-is-mcp',         'diagram',   true,  0, 0),
    ('mcp-tools',       'code',      false, 1, 2),
    ('gates',           'flow',      false, 0, 0),
    ('observability',   'code',      false, 1, 2),
    ('what-we-built',   'bullets',   false, 2, 3),
    ('takeaways',       'bullets',   false, 2, 3);

-- image_asset: Image assets with embeddings for semantic search
CREATE TABLE image_asset (
    image_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES doc(doc_id) ON DELETE CASCADE,
    storage_path    TEXT NOT NULL,              -- relative to content/images/
    caption         TEXT NOT NULL,              -- for semantic search
    alt_text        TEXT NOT NULL,              -- accessibility
    caption_embedding VECTOR(1536),             -- for semantic search
    use_cases       TEXT[] DEFAULT '{}',        -- ['architecture', 'diagram', etc.]
    license         TEXT NOT NULL,              -- mandatory per spec
    attribution     TEXT NOT NULL,              -- mandatory per spec
    style           image_style,                -- optional categorization
    width           INT,
    height          INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_image_caption_embedding ON image_asset 
    USING hnsw (caption_embedding vector_cosine_ops);
CREATE INDEX idx_image_use_cases ON image_asset USING GIN(use_cases);
CREATE INDEX idx_image_style ON image_asset(style);

-- Add optional image reference to slide
ALTER TABLE slide ADD COLUMN image_id UUID REFERENCES image_asset(image_id);

-- retrieval_log: Audit trail for all retrieval decisions
CREATE TABLE retrieval_log (
    log_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL,               -- Groups related operations
    deck_id         UUID REFERENCES deck(deck_id),
    slide_no        INT,
    query_text      TEXT NOT NULL,
    query_embedding VECTOR(1536),
    filters         JSONB DEFAULT '{}'::jsonb,
    top_k           INT NOT NULL,
    candidates      JSONB NOT NULL,              -- Array of {chunk_id, score, breakdown}
    selected        JSONB DEFAULT '[]'::jsonb,   -- Final selected chunk_ids
    latency_ms      FLOAT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_retrieval_log_run ON retrieval_log(run_id);
CREATE INDEX idx_retrieval_log_deck ON retrieval_log(deck_id, slide_no);
CREATE INDEX idx_retrieval_log_time ON retrieval_log(created_at);

-- gate_log: Audit trail for all gate decisions
CREATE TABLE gate_log (
    log_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL,
    deck_id         UUID REFERENCES deck(deck_id),
    slide_no        INT,
    gate_name       TEXT NOT NULL,               -- e.g., 'G1_retrieval', 'G2_citation'
    decision        gate_decision NOT NULL,
    score           FLOAT,                       -- Optional numeric score
    threshold       FLOAT,                       -- Threshold used for decision
    reason          TEXT,                        -- Human-readable explanation
    payload         JSONB DEFAULT '{}'::jsonb,   -- Structured details
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_gate_log_run ON gate_log(run_id);
CREATE INDEX idx_gate_log_deck ON gate_log(deck_id, slide_no);
CREATE INDEX idx_gate_log_gate ON gate_log(gate_name);
CREATE INDEX idx_gate_log_decision ON gate_log(decision);
CREATE INDEX idx_gate_log_time ON gate_log(created_at);


-- -----------------------------------------------------------------------------
-- 4. VIEWS (Agent "sensors" - observability without inference)
-- -----------------------------------------------------------------------------

-- v_deck_coverage: Which intents are covered and which are missing
CREATE OR REPLACE VIEW v_deck_coverage AS
SELECT 
    d.deck_id,
    d.topic,
    d.target_slides,
    COUNT(DISTINCT s.intent) AS covered_intents,
    COUNT(s.slide_id) AS total_slides,
    ARRAY_AGG(DISTINCT s.intent ORDER BY s.intent) FILTER (WHERE s.intent IS NOT NULL) AS covered,
    ARRAY(
        SELECT i.intent 
        FROM unnest(ARRAY['problem', 'why-postgres', 'comparison', 'capabilities', 
                          'thesis', 'schema-security', 'architecture', 'what-is-rag', 
                          'rag-in-postgres', 'advanced-retrieval', 'what-is-mcp',
                          'mcp-tools', 'gates', 'observability', 'what-we-built',
                          'takeaways']::slide_intent[]) AS i(intent)
        WHERE NOT EXISTS (
            SELECT 1 FROM slide s2 
            WHERE s2.deck_id = d.deck_id AND s2.intent = i.intent
        )
    ) AS missing
FROM deck d
LEFT JOIN slide s ON d.deck_id = s.deck_id
GROUP BY d.deck_id, d.topic, d.target_slides;

-- v_deck_health: Health metrics per deck (retries, novelty, failures)
CREATE OR REPLACE VIEW v_deck_health AS
SELECT 
    d.deck_id,
    d.topic,
    COUNT(s.slide_id) AS slide_count,
    d.target_slides,
    COALESCE(SUM(s.retry_count), 0) AS total_retries,
    ROUND(AVG(s.retry_count)::numeric, 2) AS avg_retries_per_slide,
    (SELECT COUNT(*) FROM gate_log g 
     WHERE g.deck_id = d.deck_id AND g.decision = 'fail') AS total_gate_failures,
    (SELECT COUNT(DISTINCT g.slide_no) FROM gate_log g 
     WHERE g.deck_id = d.deck_id AND g.decision = 'fail') AS slides_with_failures,
    ROUND(
        (COUNT(s.slide_id)::float / NULLIF(d.target_slides, 0) * 100)::numeric, 
        1
    ) AS completion_pct
FROM deck d
LEFT JOIN slide s ON d.deck_id = s.deck_id
GROUP BY d.deck_id, d.topic, d.target_slides;

-- v_gate_failures: Aggregated gate failure analysis
CREATE OR REPLACE VIEW v_gate_failures AS
SELECT 
    deck_id,
    gate_name,
    decision,
    reason,
    COUNT(*) AS occurrence_count,
    ROUND(AVG(score)::numeric, 3) AS avg_score,
    MIN(created_at) AS first_occurrence,
    MAX(created_at) AS last_occurrence
FROM gate_log
GROUP BY deck_id, gate_name, decision, reason
ORDER BY deck_id, gate_name, occurrence_count DESC;

-- v_top_sources: Most used chunks/docs per deck
CREATE OR REPLACE VIEW v_top_sources AS
WITH citation_chunks AS (
    SELECT 
        s.deck_id,
        jsonb_array_elements(s.citations)->>'chunk_id' AS chunk_id
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
JOIN chunk c ON c.chunk_id::text = cc.chunk_id
JOIN doc d ON c.doc_id = d.doc_id
GROUP BY cc.deck_id, c.chunk_id, d.doc_id, d.title, d.doc_type, d.trust_level
ORDER BY cc.deck_id, citation_count DESC;


-- -----------------------------------------------------------------------------
-- 5. FUNCTIONS (Deterministic logic in the database)
-- -----------------------------------------------------------------------------

-- fn_hybrid_search: Combined semantic + lexical search with RRF scoring
CREATE OR REPLACE FUNCTION fn_hybrid_search(
    p_query_embedding VECTOR(1536),
    p_query_text TEXT,
    p_filters JSONB DEFAULT '{}'::jsonb,
    p_top_k INT DEFAULT 10,
    p_semantic_weight FLOAT DEFAULT 0.7,
    p_lexical_weight FLOAT DEFAULT 0.3,
    p_rrf_k INT DEFAULT 60
)
RETURNS TABLE (
    chunk_id UUID,
    doc_id UUID,
    content TEXT,
    doc_title TEXT,
    trust_level trust_level,
    semantic_score FLOAT,
    lexical_score FLOAT,
    combined_score FLOAT,
    semantic_rank INT,
    lexical_rank INT
) AS $$
DECLARE
    v_tsquery TSQUERY;
BEGIN
    -- Build tsquery from search text
    v_tsquery := plainto_tsquery('english', unaccent(p_query_text));
    
    RETURN QUERY
    WITH semantic_results AS (
        SELECT 
            c.chunk_id,
            c.doc_id,
            c.content,
            d.title AS doc_title,
            d.trust_level,
            1 - (c.embedding <=> p_query_embedding) AS score,
            ROW_NUMBER() OVER (ORDER BY c.embedding <=> p_query_embedding) AS rank
        FROM chunk c
        JOIN doc d ON c.doc_id = d.doc_id
        WHERE c.embedding IS NOT NULL
          AND (p_filters->>'doc_type' IS NULL OR d.doc_type::text = p_filters->>'doc_type')
          AND (p_filters->>'trust_level' IS NULL OR d.trust_level::text = p_filters->>'trust_level')
          AND (p_filters->>'tags' IS NULL OR d.tags && ARRAY(SELECT jsonb_array_elements_text(p_filters->'tags')))
        ORDER BY c.embedding <=> p_query_embedding
        LIMIT p_top_k * 2  -- Get more candidates for merging
    ),
    lexical_results AS (
        SELECT 
            c.chunk_id,
            c.doc_id,
            c.content,
            d.title AS doc_title,
            d.trust_level,
            ts_rank_cd(c.tsv, v_tsquery) AS score,
            ROW_NUMBER() OVER (ORDER BY ts_rank_cd(c.tsv, v_tsquery) DESC) AS rank
        FROM chunk c
        JOIN doc d ON c.doc_id = d.doc_id
        WHERE c.tsv @@ v_tsquery
          AND (p_filters->>'doc_type' IS NULL OR d.doc_type::text = p_filters->>'doc_type')
          AND (p_filters->>'trust_level' IS NULL OR d.trust_level::text = p_filters->>'trust_level')
          AND (p_filters->>'tags' IS NULL OR d.tags && ARRAY(SELECT jsonb_array_elements_text(p_filters->'tags')))
        ORDER BY ts_rank_cd(c.tsv, v_tsquery) DESC
        LIMIT p_top_k * 2
    ),
    combined AS (
        SELECT 
            COALESCE(s.chunk_id, l.chunk_id) AS chunk_id,
            COALESCE(s.doc_id, l.doc_id) AS doc_id,
            COALESCE(s.content, l.content) AS content,
            COALESCE(s.doc_title, l.doc_title) AS doc_title,
            COALESCE(s.trust_level, l.trust_level) AS trust_level,
            COALESCE(s.score, 0) AS semantic_score,
            COALESCE(l.score, 0) AS lexical_score,
            COALESCE(s.rank, p_top_k * 2 + 1) AS semantic_rank,
            COALESCE(l.rank, p_top_k * 2 + 1) AS lexical_rank,
            -- RRF scoring: 1/(k + rank)
            (p_semantic_weight / (p_rrf_k + COALESCE(s.rank, p_top_k * 2 + 1))) +
            (p_lexical_weight / (p_rrf_k + COALESCE(l.rank, p_top_k * 2 + 1))) AS rrf_score
        FROM semantic_results s
        FULL OUTER JOIN lexical_results l ON s.chunk_id = l.chunk_id
    )
    SELECT 
        c.chunk_id,
        c.doc_id,
        c.content,
        c.doc_title,
        c.trust_level,
        c.semantic_score::FLOAT,
        c.lexical_score::FLOAT,
        c.rrf_score::FLOAT AS combined_score,
        c.semantic_rank::INT,
        c.lexical_rank::INT
    FROM combined c
    ORDER BY c.rrf_score DESC
    LIMIT p_top_k;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE  -- Queries mutable chunk table
   SET search_path = public;

-- fn_check_retrieval_quality: Gate G1 — evaluate whether search results meet quality bar
-- Thresholds default to config-table values; Python always passes explicit values.
CREATE OR REPLACE FUNCTION fn_check_retrieval_quality(
    p_search_results JSONB,
    p_min_chunks INT DEFAULT 3,
    p_min_score FLOAT DEFAULT 0.3
)
RETURNS TABLE (
    is_valid BOOLEAN,
    chunk_count INT,
    top_score FLOAT,
    errors JSONB
) AS $$
DECLARE
    v_errors JSONB := '[]'::jsonb;
    v_count INT;
    v_top_score FLOAT;
BEGIN
    -- Count results
    IF p_search_results IS NULL OR jsonb_typeof(p_search_results) != 'array' THEN
        v_count := 0;
        v_top_score := 0.0;
    ELSE
        v_count := jsonb_array_length(p_search_results);
        -- Extract top result's combined_score (results are pre-sorted by score desc)
        IF v_count > 0 THEN
            v_top_score := COALESCE(
                (p_search_results->0->>'combined_score')::FLOAT,
                0.0
            );
        ELSE
            v_top_score := 0.0;
        END IF;
    END IF;

    -- Check minimum chunk count
    IF v_count < p_min_chunks THEN
        v_errors := v_errors || jsonb_build_array(
            format('Too few chunks: %s (min: %s)', v_count, p_min_chunks)
        );
    END IF;

    -- Check top score meets quality bar
    IF v_top_score <= p_min_score THEN
        v_errors := v_errors || jsonb_build_array(
            format('Top score too low: %s (min: %s)', round(v_top_score::numeric, 3), round(p_min_score::numeric, 3))
        );
    END IF;

    RETURN QUERY SELECT
        jsonb_array_length(v_errors) = 0 AS is_valid,
        v_count AS chunk_count,
        v_top_score AS top_score,
        v_errors AS errors;
END;
$$ LANGUAGE plpgsql IMMUTABLE
   SECURITY INVOKER
   PARALLEL SAFE  -- Pure computation on input JSONB, no table access
   SET search_path = public;

-- fn_check_novelty: Check if candidate content is novel vs existing slides
CREATE OR REPLACE FUNCTION fn_check_novelty(
    p_deck_id UUID,
    p_candidate_embedding VECTOR(1536),
    p_threshold FLOAT DEFAULT 0.85
)
RETURNS TABLE (
    is_novel BOOLEAN,
    max_similarity FLOAT,
    most_similar_slide_no INT,
    most_similar_intent slide_intent
) AS $$
BEGIN
    RETURN QUERY
    WITH similarities AS (
        SELECT 
            s.slide_no,
            s.intent,
            1 - (s.content_embedding <=> p_candidate_embedding) AS similarity
        FROM slide s
        WHERE s.deck_id = p_deck_id
          AND s.content_embedding IS NOT NULL
        ORDER BY s.content_embedding <=> p_candidate_embedding
        LIMIT 1
    )
    SELECT 
        COALESCE(sim.similarity < p_threshold, true) AS is_novel,
        COALESCE(sim.similarity, 0.0)::FLOAT AS max_similarity,
        sim.slide_no::INT AS most_similar_slide_no,
        sim.intent AS most_similar_intent
    FROM (SELECT 1) AS dummy
    LEFT JOIN similarities sim ON true;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE  -- Queries mutable slide table
   SET search_path = public;

-- fn_check_grounding: Verify each bullet is semantically grounded in cited chunks (G2.5)
-- This is CRITICAL for RAG integrity - ensures slides come from sources, not hallucination
CREATE OR REPLACE FUNCTION fn_check_grounding(
    p_slide_spec JSONB,
    p_bullet_embeddings VECTOR(1536)[],
    p_threshold FLOAT DEFAULT 0.7,
    p_run_id UUID DEFAULT gen_random_uuid()
)
RETURNS TABLE (
    is_grounded BOOLEAN,
    ungrounded_bullets INT[],
    min_similarity FLOAT,
    grounding_details JSONB
) AS $$
DECLARE
    v_citations JSONB;
    v_chunk_ids UUID[];
    v_ungrounded INT[] := '{}';
    v_min_sim FLOAT := 1.0;
    v_bullet_idx INT;
    v_bullet_embedding VECTOR(1536);
    v_max_sim FLOAT;
    v_details JSONB := '[]'::jsonb;
BEGIN
    -- Extract cited chunk_ids from slide spec
    v_citations := p_slide_spec->'citations';
    IF v_citations IS NULL OR jsonb_typeof(v_citations) != 'array' THEN
        -- No citations = all bullets ungrounded
        FOR v_bullet_idx IN 1..array_length(p_bullet_embeddings, 1) LOOP
            v_ungrounded := array_append(v_ungrounded, v_bullet_idx);
        END LOOP;
        RETURN QUERY SELECT false, v_ungrounded, 0.0::FLOAT, 
            '{"error": "No citations provided"}'::jsonb;
        RETURN;
    END IF;
    
    -- Get chunk_ids from citations
    SELECT ARRAY_AGG((c.val->>'chunk_id')::UUID) INTO v_chunk_ids
    FROM jsonb_array_elements(v_citations) AS c(val)
    WHERE c.val->>'chunk_id' IS NOT NULL;
    
    IF v_chunk_ids IS NULL OR array_length(v_chunk_ids, 1) = 0 THEN
        FOR v_bullet_idx IN 1..array_length(p_bullet_embeddings, 1) LOOP
            v_ungrounded := array_append(v_ungrounded, v_bullet_idx);
        END LOOP;
        RETURN QUERY SELECT false, v_ungrounded, 0.0::FLOAT,
            '{"error": "No valid chunk_ids in citations"}'::jsonb;
        RETURN;
    END IF;
    
    -- Check each bullet against cited chunks
    FOR v_bullet_idx IN 1..array_length(p_bullet_embeddings, 1) LOOP
        v_bullet_embedding := p_bullet_embeddings[v_bullet_idx];
        
        -- Find max similarity to any cited chunk
        SELECT MAX(1 - (v_bullet_embedding <=> c.embedding)) INTO v_max_sim
        FROM chunk c
        WHERE c.chunk_id = ANY(v_chunk_ids)
          AND c.embedding IS NOT NULL;
        
        -- Default to 0 if no embeddings found
        v_max_sim := COALESCE(v_max_sim, 0.0);
        
        -- Track minimum similarity across all bullets
        IF v_max_sim < v_min_sim THEN
            v_min_sim := v_max_sim;
        END IF;
        
        -- Record details for this bullet
        v_details := v_details || jsonb_build_array(jsonb_build_object(
            'bullet_index', v_bullet_idx,
            'max_similarity', ROUND(v_max_sim::numeric, 4),
            'grounded', v_max_sim >= p_threshold
        ));
        
        -- If below threshold, mark as ungrounded
        IF v_max_sim < p_threshold THEN
            v_ungrounded := array_append(v_ungrounded, v_bullet_idx);
        END IF;
    END LOOP;
    
    RETURN QUERY SELECT 
        array_length(v_ungrounded, 1) IS NULL OR array_length(v_ungrounded, 1) = 0,
        v_ungrounded,
        v_min_sim,
        v_details;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE  -- Queries chunk table
   SET search_path = public;

-- fn_validate_slide_structure: Type-aware slide format and constraints validation
-- Resolves slide_type AND bullet defaults from intent_type_map internally
CREATE OR REPLACE FUNCTION fn_validate_slide_structure(
    p_slide_spec JSONB
)
RETURNS TABLE (
    is_valid BOOLEAN,
    errors JSONB
) AS $$
DECLARE
    v_errors JSONB := '[]'::jsonb;
    v_slide_type TEXT;
    v_min_bullets INT;
    v_max_bullets INT;
    v_max_bullet_words INT;
    v_bullets JSONB;
    v_bullet TEXT;
    v_bullet_count INT;
    v_word_count INT;
    v_i INT;
    v_cd JSONB;
    v_title TEXT;
    v_title_len INT;
    v_item TEXT;
    v_items JSONB;
    v_steps JSONB;
    v_step JSONB;
    v_code TEXT;
    v_lines TEXT[];
    v_line TEXT;
BEGIN
    v_title := p_slide_spec->>'title';
    IF v_title IS NULL OR trim(v_title) = '' THEN
        v_errors := v_errors || '["Missing or empty title"]'::jsonb;
    ELSE
        v_title_len := length(v_title);
        IF v_title_len > 60 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Title too long: %s chars (max: 60)', v_title_len));
        END IF;
        IF v_title ~ '\.$' THEN
            v_errors := v_errors || '["Title should not end with a period"]'::jsonb;
        END IF;
    END IF;

    IF p_slide_spec->>'intent' IS NULL THEN
        v_errors := v_errors || '["Missing intent"]'::jsonb;
    END IF;

    SELECT itm.slide_type::text, itm.min_bullets, itm.max_bullets, itm.max_bullet_words
    INTO v_slide_type, v_min_bullets, v_max_bullets, v_max_bullet_words
    FROM intent_type_map itm
    WHERE itm.intent = (p_slide_spec->>'intent')::slide_intent;

    v_slide_type := COALESCE(v_slide_type, 'bullets');
    v_min_bullets := COALESCE(v_min_bullets, 2);
    v_max_bullets := COALESCE(v_max_bullets, 3);
    v_max_bullet_words := COALESCE(v_max_bullet_words, 15);

    v_cd := COALESCE(p_slide_spec->'content_data', '{}'::jsonb);

    CASE v_slide_type

    WHEN 'statement' THEN
        IF v_cd->>'statement' IS NULL OR length(trim(v_cd->>'statement')) < 8 THEN
            v_errors := v_errors || '["Statement required (min 8 chars)"]'::jsonb;
        ELSIF length(v_cd->>'statement') > 90 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Statement too long: %s chars (max: 90)', length(v_cd->>'statement')));
        END IF;
        IF v_cd->>'subtitle' IS NOT NULL AND length(v_cd->>'subtitle') > 120 THEN
            v_errors := v_errors || '["Subtitle too long (max 120 chars)"]'::jsonb;
        END IF;
        v_bullets := p_slide_spec->'bullets';
        IF v_bullets IS NOT NULL AND jsonb_typeof(v_bullets) = 'array' AND jsonb_array_length(v_bullets) > 0 THEN
            v_errors := v_errors || '["Statement slides should not have bullets"]'::jsonb;
        END IF;

    WHEN 'split' THEN
        v_items := COALESCE(v_cd->'left_items', '[]'::jsonb);
        IF jsonb_typeof(v_items) != 'array' OR jsonb_array_length(v_items) < 2 OR jsonb_array_length(v_items) > 3 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Split left_items must have 2-3 items (got %s)', jsonb_array_length(COALESCE(v_items, '[]'::jsonb))));
        END IF;
        v_items := COALESCE(v_cd->'right_items', '[]'::jsonb);
        IF jsonb_typeof(v_items) != 'array' OR jsonb_array_length(v_items) < 2 OR jsonb_array_length(v_items) > 3 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Split right_items must have 2-3 items (got %s)', jsonb_array_length(COALESCE(v_items, '[]'::jsonb))));
        END IF;
        IF jsonb_array_length(COALESCE(v_cd->'left_items', '[]'::jsonb)) > 0
           AND jsonb_array_length(COALESCE(v_cd->'right_items', '[]'::jsonb)) > 0
           AND abs(jsonb_array_length(v_cd->'left_items') - jsonb_array_length(v_cd->'right_items')) > 1 THEN
            v_errors := v_errors || '["Split columns must be balanced (difference <= 1)"]'::jsonb;
        END IF;

    WHEN 'flow' THEN
        v_steps := COALESCE(v_cd->'steps', '[]'::jsonb);
        IF jsonb_typeof(v_steps) != 'array' OR jsonb_array_length(v_steps) < 4 OR jsonb_array_length(v_steps) > 7 THEN
            v_errors := v_errors || jsonb_build_array(
                format('Flow must have 4-7 steps (got %s)', jsonb_array_length(COALESCE(v_steps, '[]'::jsonb))));
        ELSE
            FOR v_i IN 0..jsonb_array_length(v_steps) - 1 LOOP
                v_step := v_steps->v_i;
                IF v_step->>'label' IS NULL OR length(v_step->>'label') < 2 OR length(v_step->>'label') > 30 THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Flow step %s label must be 2-30 chars', v_i + 1));
                END IF;
                IF v_step->>'caption' IS NOT NULL AND length(v_step->>'caption') > 60 THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Flow step %s caption too long (max 60 chars)', v_i + 1));
                END IF;
            END LOOP;
        END IF;

    WHEN 'diagram' THEN
        v_items := COALESCE(v_cd->'callouts', '[]'::jsonb);
        IF jsonb_typeof(v_items) = 'array' AND jsonb_array_length(v_items) > 3 THEN
            v_errors := v_errors || '["Diagram callouts: max 3"]'::jsonb;
        END IF;
        IF jsonb_typeof(v_items) = 'array' THEN
            FOR v_i IN 0..jsonb_array_length(v_items) - 1 LOOP
                IF length(v_items->>v_i) > 40 THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Diagram callout %s too long: %s chars (max 40)', v_i + 1, length(v_items->>v_i)));
                END IF;
            END LOOP;
        END IF;
        IF v_cd->>'caption' IS NOT NULL AND length(v_cd->>'caption') > 120 THEN
            v_errors := v_errors || '["Diagram caption too long (max 120 chars)"]'::jsonb;
        END IF;

    WHEN 'code' THEN
        v_code := v_cd->>'code_block';
        IF v_code IS NULL OR length(trim(v_code)) = 0 THEN
            v_errors := v_errors || '["Code slide requires code_block"]'::jsonb;
        ELSE
            v_lines := string_to_array(v_code, E'\n');
            IF array_length(v_lines, 1) < 8 THEN
                v_errors := v_errors || jsonb_build_array(
                    format('Code too short: %s lines (min 8)', array_length(v_lines, 1)));
            END IF;
            IF array_length(v_lines, 1) > 15 THEN
                v_errors := v_errors || jsonb_build_array(
                    format('Code too long: %s lines (max 15)', array_length(v_lines, 1)));
            END IF;
            FOREACH v_line IN ARRAY v_lines LOOP
                IF length(v_line) > 80 THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Code line exceeds 80 chars: %s', length(v_line)));
                    EXIT;
                END IF;
            END LOOP;
        END IF;
        IF v_cd->>'language' IS NULL THEN
            v_errors := v_errors || '["Code slide requires language field"]'::jsonb;
        END IF;
        v_items := COALESCE(v_cd->'explain_bullets', '[]'::jsonb);
        IF jsonb_typeof(v_items) = 'array' AND jsonb_array_length(v_items) > 2 THEN
            v_errors := v_errors || '["Code explain_bullets: max 2"]'::jsonb;
        END IF;

    ELSE
        v_bullets := p_slide_spec->'bullets';
        IF v_bullets IS NULL OR jsonb_typeof(v_bullets) != 'array' THEN
            v_errors := v_errors || '["bullets must be an array"]'::jsonb;
        ELSE
            v_bullet_count := jsonb_array_length(v_bullets);

            IF v_bullet_count < v_min_bullets THEN
                v_errors := v_errors || jsonb_build_array(
                    format('Too few bullets: %s (min: %s)', v_bullet_count, v_min_bullets));
            END IF;

            IF v_bullet_count > v_max_bullets THEN
                v_errors := v_errors || jsonb_build_array(
                    format('Too many bullets: %s (max: %s)', v_bullet_count, v_max_bullets));
            END IF;

            FOR v_i IN 0..v_bullet_count - 1 LOOP
                v_bullet := v_bullets->>v_i;
                IF v_bullet IS NOT NULL THEN
                    v_word_count := array_length(regexp_split_to_array(trim(v_bullet), '\s+'), 1);
                    IF v_word_count > v_max_bullet_words THEN
                        v_errors := v_errors || jsonb_build_array(
                            format('Bullet %s too long: %s words (max: %s)', v_i + 1, v_word_count, v_max_bullet_words));
                    END IF;
                END IF;
            END LOOP;
        END IF;

    END CASE;

    IF p_slide_spec->>'intent' IS NOT NULL
       AND p_slide_spec->>'intent' NOT IN ('title', 'thanks') THEN
        IF p_slide_spec->>'speaker_notes' IS NULL
           OR length(trim(p_slide_spec->>'speaker_notes')) < 50 THEN
            v_errors := v_errors || jsonb_build_array(
                'Speaker notes required for content slides (min 50 characters)');
        END IF;
    END IF;

    RETURN QUERY SELECT
        jsonb_array_length(v_errors) = 0 AS is_valid,
        v_errors AS errors;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL SAFE
   SET search_path = public;

-- fn_validate_citations: Ensure slide has valid citations
CREATE OR REPLACE FUNCTION fn_validate_citations(
    p_slide_spec JSONB,
    p_min_citations INT DEFAULT 1
)
RETURNS TABLE (
    is_valid BOOLEAN,
    citation_count INT,
    errors JSONB
) AS $$
DECLARE
    v_errors JSONB := '[]'::jsonb;
    v_citations JSONB;
    v_count INT;
BEGIN
    v_citations := p_slide_spec->'citations';
    
    IF v_citations IS NULL OR jsonb_typeof(v_citations) != 'array' THEN
        v_count := 0;
        v_errors := v_errors || '["citations must be an array"]'::jsonb;
    ELSE
        v_count := jsonb_array_length(v_citations);
        
        IF v_count < p_min_citations THEN
            v_errors := v_errors || jsonb_build_array(
                format('Too few citations: %s (min: %s)', v_count, p_min_citations)
            );
        END IF;
        
        -- Verify each citation references a real chunk
        IF v_count > 0 THEN
            DECLARE
                v_missing_chunks TEXT[];
            BEGIN
                SELECT ARRAY_AGG(c.chunk_id_str) INTO v_missing_chunks
                FROM (
                    SELECT jsonb_array_elements(v_citations)->>'chunk_id' AS chunk_id_str
                ) c
                WHERE NOT EXISTS (
                    SELECT 1 FROM chunk ch WHERE ch.chunk_id::text = c.chunk_id_str
                );
                
                IF v_missing_chunks IS NOT NULL AND array_length(v_missing_chunks, 1) > 0 THEN
                    v_errors := v_errors || jsonb_build_array(
                        format('Citations reference non-existent chunks: %s', v_missing_chunks)
                    );
                END IF;
            END;
        END IF;
    END IF;
    
    RETURN QUERY SELECT 
        jsonb_array_length(v_errors) = 0 AS is_valid,
        v_count AS citation_count,
        v_errors AS errors;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE  -- Queries chunk table
   SET search_path = public;

-- fn_pick_next_intent: Deterministically select the next missing intent
-- p_exclude: optional array of intents to skip (e.g. abandoned intents)
CREATE OR REPLACE FUNCTION fn_pick_next_intent(
    p_deck_id UUID,
    p_exclude  slide_intent[] DEFAULT '{}'
)
RETURNS slide_intent AS $$
DECLARE
    v_intent_order slide_intent[] := ARRAY[
        'problem', 'why-postgres', 'comparison', 'capabilities',
        'thesis', 'schema-security', 'architecture', 'what-is-rag', 
        'rag-in-postgres', 'advanced-retrieval', 'what-is-mcp',
        'mcp-tools', 'gates', 'observability', 'what-we-built',
        'takeaways'
    ]::slide_intent[];
    v_next slide_intent;
BEGIN
    -- Find the first intent in the canonical order that doesn't have a slide
    -- and is not in the exclusion list
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
   PARALLEL UNSAFE  -- Queries slide table
   SET search_path = public;

-- fn_search_images: Semantic search for images by caption/alt_text embedding
CREATE OR REPLACE FUNCTION fn_search_images(
    p_query_embedding VECTOR(1536),
    p_filters JSONB DEFAULT '{}'::jsonb,
    p_top_k INT DEFAULT 5
)
RETURNS TABLE (
    image_id UUID,
    storage_path TEXT,
    caption TEXT,
    alt_text TEXT,
    use_cases TEXT[],
    style image_style,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ia.image_id,
        ia.storage_path,
        ia.caption,
        ia.alt_text,
        ia.use_cases,
        ia.style,
        (1 - (ia.caption_embedding <=> p_query_embedding))::FLOAT AS similarity
    FROM image_asset ia
    WHERE ia.caption_embedding IS NOT NULL
      AND (p_filters->>'style' IS NULL OR ia.style::text = p_filters->>'style')
      AND (p_filters->>'use_cases' IS NULL OR ia.use_cases && ARRAY(SELECT jsonb_array_elements_text(p_filters->'use_cases')))
    ORDER BY ia.caption_embedding <=> p_query_embedding
    LIMIT p_top_k;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE
   SET search_path = public;

-- fn_commit_slide: Atomically insert/update a slide with validation
-- Gate sequence: G2 (citations) + G3 (format) validated here
-- G4 (novelty) and G2.5 (grounding) should be validated by orchestrator BEFORE calling
-- Pass their results to log the complete gate chain
CREATE OR REPLACE FUNCTION fn_commit_slide(
    p_deck_id UUID,
    p_slide_no INT,
    p_slide_spec JSONB,
    p_run_id UUID DEFAULT gen_random_uuid(),
    p_novelty_passed BOOLEAN DEFAULT NULL,      -- Result of fn_check_novelty (G4)
    p_novelty_score FLOAT DEFAULT NULL,         -- Similarity score from novelty check
    p_grounding_passed BOOLEAN DEFAULT NULL,    -- Result of fn_check_grounding (G2.5)
    p_grounding_score FLOAT DEFAULT NULL,       -- Min similarity from grounding check
    p_image_id UUID DEFAULT NULL                -- Optional image for the slide
)
RETURNS TABLE (
    success BOOLEAN,
    slide_id UUID,
    errors JSONB
) AS $$
DECLARE
    v_structure_valid BOOLEAN;
    v_structure_errors JSONB;
    v_citations_valid BOOLEAN;
    v_citations_errors JSONB;
    v_all_errors JSONB := '[]'::jsonb;
    v_slide_id UUID;
    v_intent slide_intent;
    v_expected_type slide_type;
    v_declared_type slide_type;
BEGIN
    -- G2: Validate citations
    SELECT vc.is_valid, vc.errors INTO v_citations_valid, v_citations_errors
    FROM fn_validate_citations(p_slide_spec) vc;
    
    IF NOT v_citations_valid THEN
        v_all_errors := v_all_errors || v_citations_errors;
    END IF;
    
    -- Log G2 result
    INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, reason, payload)
    VALUES (p_run_id, p_deck_id, p_slide_no, 'G2_citation',
            CASE WHEN v_citations_valid THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN v_citations_valid THEN 'Citations valid' ELSE 'Citation errors' END,
            jsonb_build_object('errors', COALESCE(v_citations_errors, '[]'::jsonb)));
    
    -- G2.5: Log grounding result (validated by orchestrator)
    IF p_grounding_passed IS NOT NULL THEN
        INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, score, threshold, reason)
        VALUES (p_run_id, p_deck_id, p_slide_no, 'G2.5_grounding',
                CASE WHEN p_grounding_passed THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
                p_grounding_score, 0.7,
                CASE WHEN p_grounding_passed THEN 'All bullets grounded in sources' ELSE 'Ungrounded bullets detected' END);
        
        IF NOT p_grounding_passed THEN
            v_all_errors := v_all_errors || '["Grounding check failed (G2.5)"]'::jsonb;
        END IF;
    END IF;
    
    -- G3: Validate structure (format/intent)
    SELECT vs.is_valid, vs.errors INTO v_structure_valid, v_structure_errors
    FROM fn_validate_slide_structure(p_slide_spec) vs;
    
    IF NOT v_structure_valid THEN
        v_all_errors := v_all_errors || v_structure_errors;
    END IF;
    
    -- Log G3 result
    INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, reason, payload)
    VALUES (p_run_id, p_deck_id, p_slide_no, 'G3_format',
            CASE WHEN v_structure_valid THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN v_structure_valid THEN 'Format valid' ELSE 'Format errors' END,
            jsonb_build_object('errors', COALESCE(v_structure_errors, '[]'::jsonb)));
    
    -- G4: Log novelty result (validated by orchestrator)
    IF p_novelty_passed IS NOT NULL THEN
        INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, score, threshold, reason)
        VALUES (p_run_id, p_deck_id, p_slide_no, 'G4_novelty',
                CASE WHEN p_novelty_passed THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
                p_novelty_score, 0.85,
                CASE WHEN p_novelty_passed THEN 'Content is novel' ELSE 'Too similar to existing slide' END);
        
        IF NOT p_novelty_passed THEN
            v_all_errors := v_all_errors || '["Novelty check failed (G4)"]'::jsonb;
        END IF;
    END IF;
    
    -- G5: Final commit gate
    INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, reason, payload)
    VALUES (p_run_id, p_deck_id, p_slide_no, 'G5_commit',
            CASE WHEN jsonb_array_length(v_all_errors) = 0 THEN 'pass'::gate_decision ELSE 'fail'::gate_decision END,
            CASE WHEN jsonb_array_length(v_all_errors) = 0 THEN 'All gates passed' ELSE 'Gate failures' END,
            jsonb_build_object('errors', v_all_errors, 'gates_logged', ARRAY['G2', 'G2.5', 'G3', 'G4', 'G5']));
    
    -- If any validation failed, return errors
    IF jsonb_array_length(v_all_errors) > 0 THEN
        RETURN QUERY SELECT false, NULL::UUID, v_all_errors;
        RETURN;
    END IF;
    
    -- Parse intent
    v_intent := (p_slide_spec->>'intent')::slide_intent;

    -- Resolve expected slide_type from intent_type_map
    SELECT itm.slide_type INTO v_expected_type
    FROM intent_type_map itm WHERE itm.intent = v_intent;

    v_expected_type := COALESCE(v_expected_type, 'bullets'::slide_type);

    v_declared_type := COALESCE(
        (p_slide_spec->>'slide_type')::slide_type,
        v_expected_type
    );
    IF v_declared_type != v_expected_type THEN
        v_all_errors := v_all_errors || jsonb_build_array(
            format('slide_type mismatch: got %s, expected %s for intent %s',
                   v_declared_type, v_expected_type, v_intent));
        RETURN QUERY SELECT false, NULL::UUID, v_all_errors;
        RETURN;
    END IF;

    -- Insert or update slide
    INSERT INTO slide (
        deck_id, slide_no, intent, title, bullets, 
        speaker_notes, citations, image_id,
        slide_type, content_data
    ) VALUES (
        p_deck_id,
        p_slide_no,
        v_intent,
        p_slide_spec->>'title',
        p_slide_spec->'bullets',
        p_slide_spec->>'speaker_notes',
        p_slide_spec->'citations',
        p_image_id,
        COALESCE((p_slide_spec->>'slide_type')::slide_type, 'bullets'::slide_type),
        COALESCE(p_slide_spec->'content_data', '{}'::jsonb)
    )
    ON CONFLICT (deck_id, slide_no) DO UPDATE SET
        intent = EXCLUDED.intent,
        title = EXCLUDED.title,
        bullets = EXCLUDED.bullets,
        speaker_notes = EXCLUDED.speaker_notes,
        citations = EXCLUDED.citations,
        image_id = EXCLUDED.image_id,
        slide_type = EXCLUDED.slide_type,
        content_data = EXCLUDED.content_data,
        retry_count = slide.retry_count + 1,
        updated_at = now()
    RETURNING slide.slide_id INTO v_slide_id;
    
    RETURN QUERY SELECT true, v_slide_id, '[]'::jsonb;
END;
$$ LANGUAGE plpgsql VOLATILE  -- Modifies data
   SECURITY INVOKER
   SET search_path = public;

-- fn_create_deck: Create a new deck with configuration
CREATE OR REPLACE FUNCTION fn_create_deck(
    p_topic TEXT,
    p_target_slides INT DEFAULT 14,
    p_style_contract JSONB DEFAULT '{}'::jsonb,
    p_description TEXT DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    v_deck_id UUID;
BEGIN
    INSERT INTO deck (topic, description, style_contract, target_slides)
    VALUES (p_topic, p_description, p_style_contract, p_target_slides)
    RETURNING deck_id INTO v_deck_id;
    
    RETURN v_deck_id;
END;
$$ LANGUAGE plpgsql VOLATILE
   SECURITY INVOKER
   SET search_path = public;

-- fn_get_run_report: Generate comprehensive report for a deck generation run
CREATE OR REPLACE FUNCTION fn_get_run_report(
    p_deck_id UUID
)
RETURNS JSONB AS $$
DECLARE
    v_report JSONB;
BEGIN
    SELECT jsonb_build_object(
        'deck_id', p_deck_id,
        'generated_at', now(),
        'summary', (
            SELECT jsonb_build_object(
                'topic', d.topic,
                'target_slides', d.target_slides,
                'actual_slides', (SELECT COUNT(*) FROM slide WHERE deck_id = p_deck_id),
                'completion_pct', h.completion_pct,
                'total_retries', h.total_retries,
                'avg_retries_per_slide', h.avg_retries_per_slide
            )
            FROM deck d
            LEFT JOIN v_deck_health h ON d.deck_id = h.deck_id
            WHERE d.deck_id = p_deck_id
        ),
        'coverage', (
            SELECT jsonb_build_object(
                'covered_intents', c.covered_intents,
                'covered', c.covered,
                'missing', c.missing
            )
            FROM v_deck_coverage c
            WHERE c.deck_id = p_deck_id
        ),
        'gate_summary', (
            SELECT jsonb_object_agg(gate_name, gate_stats)
            FROM (
                SELECT 
                    gate_name,
                    jsonb_build_object(
                        'total', COUNT(*),
                        'passed', COUNT(*) FILTER (WHERE decision = 'pass'),
                        'failed', COUNT(*) FILTER (WHERE decision = 'fail'),
                        'pass_rate', ROUND(
                            (COUNT(*) FILTER (WHERE decision = 'pass')::float / 
                             NULLIF(COUNT(*), 0) * 100)::numeric, 1
                        )
                    ) as gate_stats
                FROM gate_log
                WHERE deck_id = p_deck_id
                GROUP BY gate_name
            ) sub
        ),
        'top_failure_reasons', (
            SELECT jsonb_agg(failure_info)
            FROM (
                SELECT jsonb_build_object(
                    'gate', gate_name,
                    'reason', reason,
                    'count', COUNT(*)
                ) as failure_info
                FROM gate_log
                WHERE deck_id = p_deck_id AND decision = 'fail'
                GROUP BY gate_name, reason
                ORDER BY COUNT(*) DESC
                LIMIT 10
            ) sub
        ),
        'slides', (
            SELECT jsonb_agg(slide_info ORDER BY slide_no)
            FROM (
                SELECT jsonb_build_object(
                    'slide_no', s.slide_no,
                    'intent', s.intent,
                    'title', s.title,
                    'retry_count', s.retry_count,
                    'citation_count', jsonb_array_length(COALESCE(s.citations, '[]'::jsonb))
                ) as slide_info, s.slide_no
                FROM slide s
                WHERE s.deck_id = p_deck_id
            ) sub
        )
    ) INTO v_report;
    
    RETURN v_report;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE  -- Queries multiple tables
   SET search_path = public;

-- fn_log_retrieval: Helper to log retrieval operations
CREATE OR REPLACE FUNCTION fn_log_retrieval(
    p_run_id UUID,
    p_deck_id UUID,
    p_slide_no INT,
    p_query_text TEXT,
    p_query_embedding VECTOR(1536),
    p_filters JSONB,
    p_top_k INT,
    p_candidates JSONB,
    p_selected JSONB,
    p_latency_ms FLOAT
)
RETURNS UUID AS $$
DECLARE
    v_log_id UUID;
BEGIN
    INSERT INTO retrieval_log (
        run_id, deck_id, slide_no, query_text, query_embedding,
        filters, top_k, candidates, selected, latency_ms
    ) VALUES (
        p_run_id, p_deck_id, p_slide_no, p_query_text, p_query_embedding,
        p_filters, p_top_k, p_candidates, p_selected, p_latency_ms
    )
    RETURNING log_id INTO v_log_id;
    
    RETURN v_log_id;
END;
$$ LANGUAGE plpgsql VOLATILE
   SECURITY INVOKER
   SET search_path = public;

-- fn_log_gate: Helper to log gate decisions
CREATE OR REPLACE FUNCTION fn_log_gate(
    p_run_id UUID,
    p_deck_id UUID,
    p_slide_no INT,
    p_gate_name TEXT,
    p_decision gate_decision,
    p_score FLOAT,
    p_threshold FLOAT,
    p_reason TEXT,
    p_payload JSONB DEFAULT '{}'::jsonb
)
RETURNS UUID AS $$
DECLARE
    v_log_id UUID;
BEGIN
    INSERT INTO gate_log (
        run_id, deck_id, slide_no, gate_name, decision,
        score, threshold, reason, payload
    ) VALUES (
        p_run_id, p_deck_id, p_slide_no, p_gate_name, p_decision,
        p_score, p_threshold, p_reason, p_payload
    )
    RETURNING log_id INTO v_log_id;
    
    RETURN v_log_id;
END;
$$ LANGUAGE plpgsql VOLATILE
   SECURITY INVOKER
   SET search_path = public;


-- -----------------------------------------------------------------------------
-- 6. HELPER FUNCTIONS
-- -----------------------------------------------------------------------------

-- Get deck state as JSON (for MCP get_deck_state tool)
CREATE OR REPLACE FUNCTION fn_get_deck_state(p_deck_id UUID)
RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'deck', jsonb_build_object(
            'deck_id', d.deck_id,
            'topic', d.topic,
            'target_slides', d.target_slides,
            'created_at', d.created_at
        ),
        'coverage', (
            SELECT jsonb_build_object(
                'covered_intents', c.covered_intents,
                'total_slides', c.total_slides,
                'covered', c.covered,
                'missing', c.missing
            )
            FROM v_deck_coverage c WHERE c.deck_id = d.deck_id
        ),
        'health', (
            SELECT jsonb_build_object(
                'total_retries', h.total_retries,
                'avg_retries_per_slide', h.avg_retries_per_slide,
                'total_gate_failures', h.total_gate_failures,
                'completion_pct', h.completion_pct
            )
            FROM v_deck_health h WHERE h.deck_id = d.deck_id
        ),
        'slides', (
            SELECT jsonb_agg(jsonb_build_object(
                'slide_no', s.slide_no,
                'intent', s.intent,
                'title', s.title,
                'retry_count', s.retry_count
            ) ORDER BY s.slide_no)
            FROM slide s WHERE s.deck_id = d.deck_id
        )
    ) INTO v_result
    FROM deck d
    WHERE d.deck_id = p_deck_id;
    
    RETURN v_result;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE  -- Queries multiple tables
   SET search_path = public;


-- -----------------------------------------------------------------------------
-- 7. INITIAL DATA (Demo deck)
-- -----------------------------------------------------------------------------

-- Create a demo deck (will be populated by ingestion pipeline)
-- INSERT INTO deck (topic, description, target_slides, style_contract)
-- VALUES (
--     'Postgres as an AI Application Server',
--     'Building RAG + MCP Workflows Inside the Database - Scale23x Talk',
--     13,
--     '{"tone": "technical", "audience": "developers", "bullet_style": "concise"}'::jsonb
-- );


-- -----------------------------------------------------------------------------
-- 8. SECURITY: REVOKE DEFAULT PUBLIC ACCESS, GRANT TO APP ROLE
-- -----------------------------------------------------------------------------
-- 
-- Security Model:
-- - All functions use SECURITY INVOKER (default, safer than DEFINER)
-- - All functions have SET search_path to prevent hijacking
-- - Revoke public execute, grant only to app role
-- - App connects with limited-privilege role, not superuser
--

-- Revoke default public execute on all functions
-- (Uncomment when deploying to production)

-- REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

-- Create application role with minimal privileges
-- (Uncomment and adjust for production)

-- CREATE ROLE slidegen_app LOGIN PASSWORD 'change_me';

-- Grant table access
-- GRANT SELECT, INSERT, UPDATE, DELETE ON doc, chunk, deck, slide TO slidegen_app;
-- GRANT SELECT, INSERT ON retrieval_log, gate_log TO slidegen_app;  -- Logs are append-only

-- Grant sequence access (for UUID generation we use gen_random_uuid(), not sequences)
-- GRANT USAGE ON SCHEMA public TO slidegen_app;

-- Grant function execute
-- GRANT EXECUTE ON FUNCTION fn_hybrid_search TO slidegen_app;
-- GRANT EXECUTE ON FUNCTION fn_check_novelty TO slidegen_app;
-- GRANT EXECUTE ON FUNCTION fn_validate_slide_structure TO slidegen_app;
-- GRANT EXECUTE ON FUNCTION fn_validate_citations TO slidegen_app;
-- GRANT EXECUTE ON FUNCTION fn_pick_next_intent TO slidegen_app;
-- GRANT EXECUTE ON FUNCTION fn_commit_slide TO slidegen_app;
-- GRANT EXECUTE ON FUNCTION fn_log_retrieval TO slidegen_app;
-- GRANT EXECUTE ON FUNCTION fn_log_gate TO slidegen_app;
-- GRANT EXECUTE ON FUNCTION fn_get_deck_state TO slidegen_app;


-- =============================================================================
-- END OF SCHEMA
-- =============================================================================

-- Verify setup
DO $$
BEGIN
    RAISE NOTICE '✓ Schema created successfully';
    RAISE NOTICE '  Tables: doc, chunk, deck, slide, retrieval_log, gate_log';
    RAISE NOTICE '  Views: v_deck_coverage, v_deck_health, v_gate_failures, v_top_sources';
    RAISE NOTICE '  Functions: fn_hybrid_search, fn_check_novelty, fn_validate_*, fn_commit_slide, etc.';
    RAISE NOTICE '';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '  1. Run ingestion pipeline to populate doc/chunk tables';
    RAISE NOTICE '  2. Create a deck: INSERT INTO deck (topic, target_slides) VALUES (...)';
    RAISE NOTICE '  3. Test hybrid search: SELECT * FROM fn_hybrid_search(embedding, ''query'', ''{}'', 10)';
END $$;
