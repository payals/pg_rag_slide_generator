-- =============================================================================
-- Migration 014: Comparison run storage for multi-run aggregation
-- =============================================================================
-- Stores per-run results from compare_decks.py so multiple LLM evaluation
-- runs can be aggregated into majority-vote summaries.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS comparison_run (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      timestamptz NOT NULL DEFAULT now(),
    raw_deck_file   text NOT NULL,
    ctrl_deck_file  text NOT NULL,
    prompt_type     text NOT NULL CHECK (prompt_type IN ('guided', 'minimal')),
    model           text NOT NULL,
    temperature     float NOT NULL,
    -- Layer 2 deterministic metrics
    tfidf_coverage  float,
    semantic_sim    float,
    vocab_shared    int,
    vocab_baseline  int,
    -- Layer 3 pairwise LLM results
    comparisons     jsonb NOT NULL,
    key_differences jsonb,
    -- Summary counts
    baseline_wins   int NOT NULL,
    raw_wins        int NOT NULL,
    ties            int NOT NULL
);

CREATE INDEX idx_comparison_run_decks
    ON comparison_run (raw_deck_file, ctrl_deck_file);

CREATE INDEX idx_comparison_run_created
    ON comparison_run (created_at DESC);

COMMIT;
