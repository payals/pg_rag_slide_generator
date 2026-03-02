# Supabase: Postgres Best Practices for AI Agents

**Source:** supabase.com/blog/postgres-best-practices-for-ai-agents
**Type:** Engineering Blog
**Trust Level:** Medium-High (Supabase are pgvector contributors)

---

## Core Principle

> "Rather than building external embedding pipelines, Postgres can automate embedding generation and updates using pgvector, Queues, Cron, and Edge Functions."

## Key Best Practices

### 1. Keep Embeddings in Postgres

Don't use a separate vector database. pgvector gives you:
- ACID transactions
- JOINs with your data
- Row-level security
- Backups included
- No sync issues

### 2. Automatic Embedding Pipeline

Use Postgres-native features for embedding coordination:

```
┌─────────────────────────────────────────────────────────┐
│                  Automatic Embeddings                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Content Change                                          │
│       │                                                  │
│       ▼                                                  │
│  ┌─────────────────┐                                    │
│  │    Trigger      │  Detects INSERT/UPDATE             │
│  └────────┬────────┘                                    │
│           │                                              │
│           ▼                                              │
│  ┌─────────────────┐                                    │
│  │    pgmq         │  Queue the embedding job           │
│  └────────┬────────┘                                    │
│           │                                              │
│           ▼                                              │
│  ┌─────────────────┐                                    │
│  │    pg_cron      │  Process queue periodically        │
│  └────────┬────────┘                                    │
│           │                                              │
│           ▼                                              │
│  ┌─────────────────┐                                    │
│  │    pg_net       │  Call embedding API                │
│  └────────┬────────┘                                    │
│           │                                              │
│           ▼                                              │
│  ┌─────────────────┐                                    │
│  │   pgvector      │  Store embedding                   │
│  └─────────────────┘                                    │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 3. Vector Index Selection

| Index Type | Best For |
|------------|----------|
| **HNSW** | Production (better recall, more robust) |
| **IVFFlat** | Large datasets, faster build time |

```sql
-- Recommended: HNSW with cosine distance
CREATE INDEX ON documents 
USING hnsw (embedding vector_cosine_ops);
```

### 4. Compute Sizing

Match your compute to your embedding dimensions:

| Embedding Dims | Vector Count | Recommended Size |
|----------------|--------------|------------------|
| 384 | 100K | Micro |
| 1536 | 100K | Small |
| 1536 | 1M+ | Large+ |

### 5. Distance Operators

| Operator | When to Use |
|----------|-------------|
| `<=>` | Text embeddings (cosine) |
| `<->` | When magnitude matters (L2) |
| `<#>` | Pre-normalized vectors (inner product) |

## Benefits of Postgres-Native Approach

1. **No drift**: Embeddings always match content
2. **No separate workers**: Database handles it
3. **Scheduled reprocessing**: pg_cron re-runs jobs on a schedule, so failed embeddings are picked up on the next cycle (retry logic must be built into the job itself)
4. **Transactional**: Content + embedding update atomically
5. **SQL-based**: Query and manage with familiar tools

## Example: Hybrid Search Query

```sql
-- Combine vector search with full-text search using RRF
-- (Reciprocal Rank Fusion avoids mixing scores on different scales)
WITH semantic AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank
    FROM documents
    ORDER BY embedding <=> $1
    LIMIT 20
),
keyword AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, plainto_tsquery($2)) DESC) AS rank
    FROM documents
    WHERE tsv @@ plainto_tsquery($2)
    LIMIT 20
)
SELECT 
    COALESCE(s.id, k.id) AS id,
    COALESCE(0.7 / (60 + s.rank), 0) + COALESCE(0.3 / (60 + k.rank), 0) AS rrf_score
FROM semantic s
FULL OUTER JOIN keyword k ON s.id = k.id
ORDER BY rrf_score DESC
LIMIT 10;
```

> **Note:** This example uses Reciprocal Rank Fusion (RRF) rather than a weighted sum of raw scores. Cosine similarity (0–1) and ts_rank (unbounded) are on different scales, so summing them directly produces unreliable rankings. RRF merges rank positions instead, avoiding the normalization problem.

---

*Fetched: 2026-02-03*
