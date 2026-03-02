# pg_trgm - PostgreSQL Trigram Extension

**Source:** PostgreSQL official documentation
**Type:** Official Documentation
**Trust Level:** High

---

## What is pg_trgm?

pg_trgm is a PostgreSQL extension that provides functions and operators for determining the similarity of text based on trigram matching.

**A trigram** is a group of three consecutive characters from a string.

## How It Works

The module extracts trigrams from strings and counts shared trigrams to measure similarity.

```
Example: "cat" produces trigrams:
  "  c", " ca", "cat", "at "
  (spaces are added for word boundaries)

"fog" produces:
  "  f", " fo", "fog", "og "

Similarity("cat", "cat") = 1.0 (identical)
Similarity("cat", "car") ≈ 0.33 (share 2 of 6 unique trigrams)
Similarity("cat", "fog") = 0.0 (no shared trigrams)
```

## Installation

```sql
CREATE EXTENSION pg_trgm;
```

## Key Functions

### similarity(text, text)
Returns a number from 0 to 1 indicating string similarity.

```sql
SELECT similarity('word', 'world');
-- Returns: 0.4 (some overlap)

SELECT similarity('PostgreSQL', 'Postgres');  
-- Returns: 0.6 (high overlap)
```

### show_trgm(text)
Returns all trigrams in a string.

```sql
SELECT show_trgm('cat');
-- Returns: {"  c"," ca","at ","cat"}
```

### word_similarity(text, text)
Returns similarity between first string and best matching extent of second.

```sql
SELECT word_similarity('word', 'this is a word');
-- Returns: 1.0 (exact match within the string)
```

## Operators

| Operator | Description |
|----------|-------------|
| `%` | Returns true if similarity > threshold |
| `<%` | Returns true if word_similarity > threshold |
| `<->` | Distance (1 - similarity) |
| `<<->` | Distance (1 - word_similarity) |

```sql
-- Find similar strings
SELECT * FROM products 
WHERE name % 'postgresql'
ORDER BY name <-> 'postgresql'
LIMIT 5;
```

## Indexing

pg_trgm supports GiST and GIN indexes for fast similarity search:

```sql
-- GIN index (faster for search)
CREATE INDEX trgm_idx ON products 
USING GIN (name gin_trgm_ops);

-- GiST index (faster for nearest-neighbor)
CREATE INDEX trgm_idx ON products 
USING GIST (name gist_trgm_ops);
```

## Use Cases in AI/RAG

### 1. Fuzzy Search
Handle typos and misspellings in user queries:
```sql
SELECT * FROM chunks 
WHERE content % 'postgreSQL'  -- Matches "PostgreSQL", "Postgres"
ORDER BY content <-> 'postgreSQL'
LIMIT 10;
```

### 2. Hybrid Search (with pgvector)
Combine semantic (vector) and lexical (trigram) search:
```sql
-- Semantic score + lexical score
SELECT 
    chunk_id,
    1 - (embedding <=> query_embedding) AS semantic_score,
    similarity(content, 'search term') AS lexical_score
FROM chunks
WHERE content % 'search term'  -- Pre-filter
ORDER BY semantic_score * 0.7 + lexical_score * 0.3 DESC
LIMIT 10;
```

### 3. Deduplication
Find near-duplicate content:
```sql
SELECT a.id, b.id, similarity(a.content, b.content)
FROM chunks a, chunks b
WHERE a.id < b.id
  AND similarity(a.content, b.content) > 0.8;
```

## Why pg_trgm + pgvector?

| Feature | pgvector | pg_trgm |
|---------|----------|---------|
| **Semantic meaning** | ✅ Excellent | ❌ None |
| **Exact keywords** | ❌ May miss | ✅ Excellent |
| **Typo tolerance** | ❌ Depends on embedding | ✅ Built-in |
| **Speed** | Fast with index | Fast with index |

**Together they provide hybrid search**: semantic understanding + keyword matching.

---

*Fetched: 2026-02-03*
