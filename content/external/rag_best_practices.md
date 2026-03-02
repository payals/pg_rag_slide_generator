# RAG Best Practices

**Source:** Industry patterns, LangChain documentation, production experience
**Type:** Implementation Guide
**Trust Level:** High

---

## Chunking Best Practices

### Chunk Size Recommendations

| Use Case | Chunk Size | Overlap |
|----------|------------|---------|
| Short answers | 256-512 tokens | 10% |
| General Q&A | 512-1024 tokens | 15% |
| Long context | 1024-2048 tokens | 20% |

**Key principle:** Chunks should be large enough to contain meaningful context but small enough to fit multiple in a prompt.

### Chunking Strategy

1. **Respect document structure** - Split on paragraph boundaries, not mid-sentence
2. **Preserve hierarchy** - Include section headers in chunk metadata
3. **Use overlap** - 10-20% overlap prevents context loss at boundaries
4. **Track position** - Store chunk index for reconstruction

```
Document → Sections → Paragraphs → Chunks (with overlap)
                                       ↓
                              Store: content + metadata + embedding
```

---

## Retrieval Best Practices

### Hybrid Search

Combine semantic and lexical search for best results:

| Search Type | Strengths | Weaknesses |
|-------------|-----------|------------|
| **Semantic (vector)** | Conceptual similarity | Misses exact terms |
| **Lexical (keyword)** | Exact matches, proper nouns | Misses synonyms |
| **Hybrid** | Best of both | More complexity |

**RRF (Reciprocal Rank Fusion):**
```
combined_score = 1/(k + semantic_rank) + 1/(k + lexical_rank)
```

### Pre-filtering

Apply metadata filters BEFORE similarity search:
- Filter by document type, trust level, tags
- Reduces search space, improves relevance
- More efficient than post-filtering

### Diversity

Avoid all results from single source:
- Use MMR (Maximal Marginal Relevance)
- Or: limit results per document
- Ensures varied perspectives in context

---

## Two-Stage Retrieval: RRF + Cross-Encoder Reranking

Production RAG systems benefit from a two-stage retrieval pipeline that separates fast recall from precise reranking.

### Stage 1: Hybrid Search with RRF in Postgres

The first stage retrieves a broad candidate set (typically 50 rows) using Reciprocal Rank Fusion (RRF) to combine pgvector cosine similarity with tsvector lexical search, all inside a single Postgres query:

```sql
WITH semantic AS (
    SELECT chunk_id, ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank
    FROM content_chunk LIMIT 50
),
lexical AS (
    SELECT chunk_id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(search_tsv, q) DESC) AS rank
    FROM content_chunk, plainto_tsquery('english', $2) q
    WHERE search_tsv @@ q LIMIT 50
)
SELECT COALESCE(s.chunk_id, l.chunk_id) AS chunk_id,
       COALESCE(1.0/(60 + s.rank), 0) + COALESCE(1.0/(60 + l.rank), 0) AS rrf_score
FROM semantic s FULL OUTER JOIN lexical l USING (chunk_id)
ORDER BY rrf_score DESC LIMIT 50;
```

RRF with k=60 balances the two ranking signals without requiring score normalization. This runs entirely inside Postgres, leveraging the HNSW index on embeddings and the GIN index on tsvector.

### Stage 2: Cross-Encoder Reranking in Python

The second stage rescores the top-50 candidates using a cross-encoder model (`cross-encoder/ms-marco-MiniLM-L6-v2`) that evaluates each query-passage pair jointly:

```python
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2")
pairs = [(query, chunk.body) for chunk in candidates]
scores = reranker.predict(pairs)
top_k = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)[:10]
```

Unlike bi-encoder embeddings that encode query and passage independently, a cross-encoder attends to both simultaneously via cross-attention layers. This produces significantly higher precision at the cost of latency (~50-100ms for 50 pairs on CPU). The trade-off is worthwhile because only 50 candidates need rescoring, not the full corpus.

### Why Two Stages?

| Stage | Where | Speed | Precision | Purpose |
|-------|-------|-------|-----------|---------|
| **Stage 1: RRF** | Postgres | <20ms | Good (recall-optimized) | Cast a wide net across the corpus |
| **Stage 2: Cross-encoder** | Python | ~80ms | Excellent (precision-optimized) | Rerank the narrow candidate set |

Vector cosine similarity is fast but coarse: it compares independent embeddings. Cross-encoders jointly attend to query and passage tokens, capturing nuanced relevance that bi-encoders miss. The two-stage design keeps latency under 100ms total while achieving near-optimal ranking quality.

---

## RAG in Postgres: Working SQL Patterns

These queries run against the actual project schema (`chunk`, `doc` tables with pgvector embeddings and tsvector columns). Each is a self-contained pattern for a different stage of the RAG pipeline inside Postgres.

### Pattern 1: Hybrid Search with RRF (Primary — use this for rag-in-postgres slides)

This is the core RAG retrieval query. It demonstrates all three search techniques in one statement: semantic similarity via pgvector, lexical matching via tsvector, and Reciprocal Rank Fusion to combine them without score normalization.

```sql
-- SEMANTIC ARM: pgvector cosine similarity (HNSW index)
WITH sem AS (
  SELECT chunk_id, ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS r
  FROM chunk WHERE embedding IS NOT NULL LIMIT 20
),
-- LEXICAL ARM: tsvector full-text search (GIN index)
lex AS (
  SELECT chunk_id, ROW_NUMBER() OVER (
    ORDER BY ts_rank_cd(tsv, plainto_tsquery($2)) DESC) AS r
  FROM chunk WHERE tsv @@ plainto_tsquery($2) LIMIT 20
)
-- RRF FUSION: merge ranks, not scores (k=60)
SELECT COALESCE(s.chunk_id, l.chunk_id) AS chunk_id,
       0.7/(60+COALESCE(s.r,41)) + 0.3/(60+COALESCE(l.r,41)) AS rrf
FROM sem s FULL OUTER JOIN lex l USING (chunk_id)
ORDER BY rrf DESC LIMIT 10;
```

`$1` is the query embedding (vector(1536)), `$2` is the raw query text. The HNSW index handles the semantic arm; the GIN index handles the lexical arm. Both arms run in under 20ms. RRF with k=60 merges rank positions instead of raw scores, avoiding the normalization problem of mixing cosine similarity (0–1) with ts_rank (unbounded).

### Pattern 2: Semantic Search with Trust-Level Filtering

Pre-filter by document trust level before vector similarity. JOINs metadata with vectors in a single query — something external vector databases cannot do.

```sql
SELECT c.chunk_id,
       d.title                              AS source,
       d.trust_level::text                  AS trust,
       1 - (c.embedding <=> $1)             AS similarity
FROM chunk c
JOIN doc d ON c.doc_id = d.doc_id
WHERE c.embedding IS NOT NULL
  AND d.trust_level IN ('high', 'medium')
ORDER BY c.embedding <=> $1
LIMIT 10;
```

The WHERE clause on `trust_level` narrows the search space before the HNSW index scan. This is the Postgres advantage: relational filters and vector search in one transaction.

### Pattern 3: Grounding Verification (Post-Generation)

After the LLM generates bullet points, verify each one is semantically grounded in the cited source chunks. This prevents hallucination at the database level.

```sql
SELECT b.ord                              AS bullet_idx,
       MAX(1 - (b.emb <=> c.embedding))   AS max_sim,
       MAX(1 - (b.emb <=> c.embedding)) >= 0.7 AS grounded
FROM unnest($1::vector(1536)[])
       WITH ORDINALITY AS b(emb, ord)
CROSS JOIN chunk c
WHERE c.chunk_id = ANY($2::uuid[])
  AND c.embedding IS NOT NULL
GROUP BY b.ord
ORDER BY b.ord;
```

`$1` is an array of bullet embeddings, `$2` is the array of cited chunk UUIDs. Any bullet with max similarity below 0.7 is flagged as ungrounded. This runs as a gate check before committing a slide.

---

## Common Pitfalls

### 1. Chunks Too Large
- **Problem:** Won't fit in context window
- **Solution:** Target 512-1024 tokens max

### 2. No Overlap
- **Problem:** Important context lost at boundaries
- **Solution:** 10-20% overlap between chunks

### 3. No Metadata
- **Problem:** Can't cite sources, can't filter
- **Solution:** Always store source, page, section

### 4. Poor Splitting
- **Problem:** Breaks mid-sentence or mid-thought
- **Solution:** Split on natural boundaries (paragraphs, sections)

### 5. Wrong Embedding Model
- **Problem:** Domain mismatch hurts retrieval
- **Solution:** Use domain-appropriate model or fine-tune

### 6. No Reranking
- **Problem:** First-pass retrieval not optimal
- **Solution:** Second-pass reranking (optional for small corpus)

### 7. Ignoring Failures
- **Problem:** No handling when retrieval fails
- **Solution:** Fallback strategies, logging, alerts

---

## Quality Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Retrieval precision** | >80% relevant in top-5 | Manual review |
| **Recall** | Find relevant docs | Test with known queries |
| **Latency** | <200ms P95 | Measure query time |
| **Citation density** | ≥1 per generated item | Automated count |

---

## Production Checklist

- [ ] Chunk size appropriate for use case
- [ ] Overlap prevents boundary issues
- [ ] Metadata enables filtering and citation
- [ ] Hybrid search combines semantic + lexical
- [ ] Diversity prevents single-source bias
- [ ] Failures are logged and handled
- [ ] Quality metrics are tracked
- [ ] Embeddings are cached (expensive to regenerate)
- [ ] Index is versioned (track changes)

---

*Extracted: 2026-02-03*
