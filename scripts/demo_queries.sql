-- ============================================================
-- Demo Day SQL Queries
-- Replace <DECK_ID> with the actual deck UUID before the demo
-- ============================================================

-- 1. Show coverage (empty deck -- before generation)
SELECT covered_intents, array_length(missing, 1) as missing_count
FROM v_deck_coverage
WHERE deck_id = '<DECK_ID>';

-- 2. Show coverage (after generation)
SELECT covered_intents, total_slides, missing
FROM v_deck_coverage
WHERE deck_id = '<DECK_ID>';

-- 3. Show gate log (validation decisions)
SELECT gate_name, decision, round(score::numeric, 3) as score
FROM gate_log
WHERE deck_id = '<DECK_ID>'
ORDER BY created_at
LIMIT 20;

-- 4. Show deck health
SELECT slide_count, total_retries, avg_retries_per_slide, completion_pct
FROM v_deck_health
WHERE deck_id = '<DECK_ID>';

-- 5. Show top sources (which documents were cited most)
SELECT doc_title, citation_count
FROM v_top_sources
WHERE deck_id = '<DECK_ID>'
ORDER BY citation_count DESC;

-- 6. Show failure scenario (gate failures with reasons)
SELECT gate_name, decision, round(score::numeric, 3) as score, reason
FROM gate_log
WHERE deck_id = '<DECK_ID>' AND decision = 'fail'
ORDER BY created_at;

-- 7. Show novelty gate fail-then-pass sequence
SELECT gate_name, decision, round(score::numeric, 3) as score, reason
FROM gate_log
WHERE deck_id = '<DECK_ID>' AND gate_name = 'g4_novelty'
ORDER BY created_at;

-- 8. Quick data check
SELECT
    (SELECT COUNT(*) FROM doc) as total_docs,
    (SELECT COUNT(*) FROM chunk) as total_chunks,
    (SELECT COUNT(*) FROM slide WHERE deck_id = '<DECK_ID>') as slides_generated;
