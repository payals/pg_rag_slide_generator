# Observability

Every gate decision, retrieval operation, and generation run is logged to Postgres. No external observability stack required.

## Audit Tables

| Table | What it captures | Rows per run |
|-------|-----------------|-------------|
| `gate_log` | Every gate decision: gate name, pass/fail, score, threshold, reason, full payload JSONB | ~100 |
| `retrieval_log` | Every hybrid search: query text, candidate count, selected count, latency in ms | ~17 |
| `generation_run` | Run-level summary: slides generated/failed, total retries, LLM calls, prompt/completion/embedding tokens, estimated cost, status, error | 1 |

## Database Views

| View | Question it answers | Key columns |
|------|-------------------|-------------|
| `v_deck_coverage` | Which intents are covered vs. missing? | `deck_id`, `intent`, `is_covered`, `slide_count` |
| `v_deck_health` | How healthy is the generation? | `deck_id`, `total_retries`, `failed_slides`, `completion_pct` |
| `v_gate_failures` | Which gates fail most, and why? | `gate_name`, `reason`, `failure_count` |
| `v_top_sources` | Which documents/chunks are most cited? | `deck_id`, `chunk_id`, `doc_title`, `citation_count` |

## Run Reports

CLI tool for post-run analysis:

```bash
python -m src.run_report --deck-id <uuid> --verbose
```

Output includes:
- Run status, duration, and slide count
- Cost breakdown (prompt tokens, completion tokens, embedding tokens, total USD)
- Gate pass/fail statistics
- Per-slide details (intent, type, retries, gate results) in verbose mode
- Top cited sources

Uses Rich for formatted terminal output, with plain-text fallback.

## Cost Tracking

Token accounting happens in the orchestrator and is written to `generation_run` at completion.

| Token type | Rate (per 1K) | Config key |
|-----------|--------------|---------|
| Prompt tokens | $0.03 | `llm_input_cost_per_1k` |
| Completion tokens | $0.06 | `llm_output_cost_per_1k` |
| Embedding tokens | $0.00002 | `embedding_cost_per_1k` |

Cost is estimated per LLM call and accumulated in `OrchestratorState.estimated_cost_usd`. When `cost_limit_usd` (default $10.00) is reached, generation ends with `cost_limited` status.

Token counts are accumulated in Python and written once at run completion — not per slide.

## Metabase Setup

Optional visual dashboard via Metabase (Docker):

```bash
docker run -d -p 3000:3000 --name metabase metabase/metabase
```

1. Open `http://localhost:3000`
2. Add database: PostgreSQL, connect to `slidegen` DB
3. Query the views (`v_deck_coverage`, `v_deck_health`, `v_gate_failures`, `v_top_sources`) directly
4. Build dashboards from `gate_log` and `retrieval_log` for custom analysis

## Useful Queries

### Gate pass rate by gate name

```sql
SELECT gate_name,
       COUNT(*) FILTER (WHERE decision = 'pass') AS passes,
       COUNT(*) FILTER (WHERE decision = 'fail') AS fails,
       ROUND(100.0 * COUNT(*) FILTER (WHERE decision = 'pass') / COUNT(*), 1) AS pass_pct
FROM gate_log
WHERE run_id = '<run-id>'
GROUP BY gate_name
ORDER BY gate_name;
```

### Which slides failed grounding?

```sql
SELECT gl.gate_name, s.intent, s.title, gl.score, gl.threshold, gl.reason
FROM gate_log gl
JOIN slide s ON s.deck_id = (SELECT deck_id FROM generation_run WHERE run_id = gl.run_id)
  AND s.slide_no = (gl.payload->>'slide_no')::int
WHERE gl.gate_name = 'g2_5_grounding'
  AND gl.decision = 'fail'
  AND gl.run_id = '<run-id>';
```

### Total cost for a deck

```sql
SELECT run_id, slides_generated, slides_failed,
       prompt_tokens, completion_tokens, embedding_tokens,
       estimated_cost_usd, status
FROM generation_run
WHERE deck_id = '<deck-id>'
ORDER BY created_at DESC;
```

### Retrieval latency percentiles

```sql
SELECT
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99
FROM retrieval_log
WHERE run_id = '<run-id>';
```

### Most cited sources

```sql
SELECT * FROM v_top_sources
WHERE deck_id = '<deck-id>'
ORDER BY citation_count DESC
LIMIT 10;
```

### Recent gate failures with details

```sql
SELECT gate_name, decision, score, threshold, reason,
       payload->>'details' AS details,
       created_at
FROM gate_log
WHERE run_id = '<run-id>'
  AND decision = 'fail'
ORDER BY created_at DESC;
```
