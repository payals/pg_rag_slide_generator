# pgvector - PostgreSQL Vector Extension

**Source:** github.com/pgvector/pgvector, PostgreSQL docs
**Type:** Official Documentation
**Trust Level:** High

---

## What is pgvector?

pgvector is an open-source PostgreSQL extension that enables vector similarity search and storage of high-dimensional embeddings directly in PostgreSQL.

**Key benefits:**
- ACID compliance
- Point-in-time recovery
- JOINs with other tables
- All standard PostgreSQL features
- No separate infrastructure needed

## Installation

```sql
-- Enable the extension
CREATE EXTENSION vector;
```

Supports PostgreSQL 12+.

## Vector Data Types

| Type | Description | Max Dimensions |
|------|-------------|----------------|
| `vector` | Standard float vectors | 16,000 (raised from 2,000 in v0.7.0) |
| `halfvec` | Half-precision vectors | 16,000 (raised from 4,000 in v0.7.0) |
| `sparsevec` | Sparse vectors | Large |
| `bit` | Binary vectors | 64,000 |

## Creating Vector Columns

```sql
-- Create a table with a vector column
CREATE TABLE items (
    id bigserial PRIMARY KEY,
    content text,
    embedding vector(1536)  -- OpenAI text-embedding-3-small dimensions
);

-- Insert vectors
INSERT INTO items (content, embedding) 
VALUES ('Hello world', '[0.1, 0.2, ...]');
```

## Distance Operators

| Operator | Distance Metric | Use Case |
|----------|----------------|----------|
| `<->` | L2 (Euclidean) | General similarity |
| `<#>` | Negative inner product | When vectors are normalized |
| `<=>` | Cosine distance | Text embeddings (recommended) |
| `<+>` | L1 (Manhattan) | Sparse data |

## Querying Vectors

```sql
-- Find 5 most similar items
SELECT id, content, embedding <=> '[0.1, 0.2, ...]' AS distance
FROM items
ORDER BY embedding <=> '[0.1, 0.2, ...]'
LIMIT 5;

-- With filtering
SELECT * FROM items
WHERE category = 'technical'
ORDER BY embedding <=> query_embedding
LIMIT 10;
```

## Indexing

### HNSW (Recommended)

Hierarchical Navigable Small World - best for most use cases.

```sql
CREATE INDEX ON items 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

Parameters:
- `m`: Max connections per node (default 16)
- `ef_construction`: Build-time quality (default 64)

### IVFFlat

Inverted File Flat - faster to build, good for large datasets.

```sql
CREATE INDEX ON items 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

## Use Cases

- **RAG applications**: Retrieve relevant context for LLMs
- **Semantic search**: Find similar documents
- **Recommendation engines**: Find similar items
- **Image similarity**: Compare image embeddings
- **Anomaly detection**: Find outliers

## Best Practices

1. **Choose the right dimensions**: Match your embedding model
2. **Use HNSW for production**: Better recall and performance
3. **Filter before vector search**: Use WHERE clauses to reduce candidates
4. **Monitor with EXPLAIN ANALYZE**: Verify index usage

## Limitations

- Performance degrades above ~50M vectors (consider pgvectorscale)
- Memory usage scales with vector dimensions
- Exact search can be slow for large datasets

---

*Fetched: 2026-02-03*
