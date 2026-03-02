# Retrieval-Augmented Generation (RAG)

**Source:** Lewis et al. 2020 paper, NVIDIA, OpenAI documentation
**Type:** Concept Overview
**Trust Level:** High

---

## What is RAG?

RAG (Retrieval-Augmented Generation) is a technique that enhances LLM responses by retrieving relevant information from external sources before generating an answer.

**Origin:** Introduced by Patrick Lewis et al. in the 2020 paper "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks" (NeurIPS 2020, 10,000+ citations).

## The Problem RAG Solves

LLMs have two key limitations:
1. **Knowledge cutoff**: Training data has a date limit
2. **Hallucination**: Models generate plausible but incorrect information

RAG addresses both by grounding responses in retrieved facts.

## How RAG Works

```
┌─────────────────────────────────────────────────────────┐
│                     RAG Pipeline                         │
└─────────────────────────────────────────────────────────┘

     User Query
          │
          ▼
┌─────────────────┐
│   1. EMBED      │  Convert query to vector
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   2. RETRIEVE   │  Find similar documents in vector DB
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   3. AUGMENT    │  Add retrieved context to prompt
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   4. GENERATE   │  LLM generates answer using context
└────────┬────────┘
         │
         ▼
     Response with citations
```

## Key Components

### 1. Document Processing
- **Chunking**: Split documents into smaller pieces
- **Embedding**: Convert chunks to vectors
- **Storage**: Store vectors in database (e.g., pgvector)

### 2. Retrieval
- **Semantic search**: Find conceptually similar content
- **Keyword search**: Find exact term matches
- **Hybrid search**: Combine both approaches

### 3. Generation
- **Context injection**: Add retrieved chunks to prompt
- **Citation tracking**: Link output to sources
- **Grounding**: Ensure output matches sources

## Why RAG vs Fine-Tuning?

| Aspect | RAG | Fine-Tuning |
|--------|-----|-------------|
| **Knowledge updates** | Add new docs anytime | Retrain model |
| **Cost** | Cheaper (inference only) | Expensive (training) |
| **Citations** | Natural (from retrieval) | Difficult |
| **Hallucination** | Reduced (grounded) | Still possible |
| **Domain adaptation** | Fast | Slow |

## RAG Benefits

1. **Reduced hallucination**: Answers grounded in real documents
2. **Source citation**: Can point to where information came from
3. **Up-to-date info**: Add new documents without retraining
4. **Domain-specific**: Works with proprietary/internal data
5. **Cost-effective**: No model training required

## Common Pitfalls

1. **Poor chunking**: Chunks too big or too small
2. **No overlap**: Important context lost at boundaries
3. **Wrong embedding model**: Domain mismatch
4. **No reranking**: Low-quality results
5. **Ignoring failures**: No handling when retrieval fails

## RAG in Production

Modern RAG systems include:
- **Hybrid search**: Vector + keyword
- **Reranking**: Improve result quality
- **Filters**: Metadata-based filtering
- **Evaluation**: Measure retrieval quality
- **Monitoring**: Track failures and quality

---

*Fetched: 2026-02-03*
