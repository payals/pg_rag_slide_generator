# Thesis

**Postgres is the control plane. The LLM is a contractor.**

## The Argument

As AI systems evolve from chat interfaces into autonomous agents, the most important component is no longer the model — it's the database beneath it. Postgres is the ideal foundation for trustworthy AI because it already provides what AI systems need: durable memory, expressive retrieval, transactional guarantees, auditing, and safe interfaces for executing real work.

This system demonstrates the thesis by turning Postgres into a full AI application server and control plane. The LLM's role is reduced to a single responsibility: drafting content. Everything else — validation, configuration, state management, retrieval, and observability — is owned by Postgres.

## What This Means in Practice

| Responsibility | Owner | How |
|---------------|-------|-----|
| Validation | Postgres | SQL gate functions (G0–G5) enforce citation integrity, semantic grounding, format compliance, novelty |
| Configuration | Postgres | 7 config tables (including `config`) replace ~450 lines of hardcoded Python constants |
| State management | Postgres | `deck.status`, `generation_run`, `slide` tables track every lifecycle transition |
| Retrieval | Postgres | `fn_hybrid_search` combines pgvector semantic search + tsvector lexical search via RRF |
| Observability | Postgres | `gate_log`, `retrieval_log`, `generation_run` + 4 views for live monitoring |
| Content drafting | LLM (GPT-5) | Produces structured slide specs from retrieved context and prompt templates |
| Loop orchestration | Python (LangGraph) | Routes gate results, counts retries, tracks cost — makes no quality decisions |

Python makes **zero quality decisions**. It orchestrates the loop. The LLM proposes. Postgres disposes.

## Before/After: What Moved to Postgres

| Aspect | Before (Python-only) | After (Postgres-consolidated) |
|--------|---------------------|-------------------------------|
| Slide type contract | Hardcoded dict, no validation | DB-enforced via triggers and FKs |
| Prompt-renderer coupling | Implicit (hope they match) | Explicit (`content_fields` JSONB validated against `html_fragment`) |
| Adding a slide type | Edit ~4 places in one file | INSERT one row in `slide_type_config` |
| Field-name references | Duplicated in ~8 locations | Single source: `content_fields` JSONB |
| Citation stripping | Hardcoded field lists | Data-driven via `walk_content_data()` |
| Text extraction | Hardcoded traversal | Single trigger, read result from DB |
| Template duplication | Separate if/elif chains in two files | Eliminated via include + DB composition |
| Configuration audit trail | `git log` only | `git log` + DB `updated_at` + gate_log |
| A/B testing prompts | Edit code, redeploy | UPDATE + restart (partial unique index enforces single-active) |
| Broken contract detection | Runtime (silent rendering failure) | INSERT/UPDATE time (exception from trigger) |
| Run tracking | None | `generation_run` table with cost/timing/status |
| Deck lifecycle | Unknown | `deck.status` column with enum transitions |

**Result:** ~450 lines of hardcoded configuration deleted. ~100 lines of loader functions added. Net reduction of ~300 lines.

## Proof Points

### 1. Adding a slide type is (almost) pure SQL

One `INSERT INTO slide_type_config` with the prompt schema, content fields, and HTML fragment. The `fn_validate_type_config` trigger validates the contract at INSERT time. No code change required — `_FRAGMENT_ORDER` is now derived dynamically from the DB.

### 2. Prompt A/B testing via DB row

Deactivate the current prompt, insert a new version. The partial unique index on `prompt_template(purpose) WHERE is_active` enforces exactly one active prompt per purpose. No code change, no redeployment — restart to pick up the new cached value.

### 3. Gate enforcement at INSERT time

`fn_commit_slide` re-validates G2 (citations) and G3 (format) at commit time, regardless of what the orchestrator thinks it already checked. A bug in the orchestrator can't bypass validation.

### 4. Full audit trail in gate_log

Every gate decision — pass or fail — is written with the score, threshold, reason, and full payload. The `v_gate_failures` view aggregates failure patterns. A human operator can diagnose "why did this slide fail?" with a single SQL query.

### 5. Views as active agent sensors

The orchestrator doesn't maintain its own coverage state — it queries `v_deck_coverage` from Postgres. The database is the single source of truth about what exists, and the agent reads it through views that pre-aggregate the answer.

## The Recursive Demo

This system generates its own talk slides. The content in the knowledge base describes Postgres as an AI control plane. The orchestrator uses Postgres as an AI control plane to generate a presentation about using Postgres as an AI control plane.

The thesis proves itself.

## Talk Abstract

> As AI systems evolve from simple chat interfaces into fully autonomous assistants, developers are learning that the most important component is no longer the model. It is the database beneath it. Postgres is emerging as the ideal foundation for trustworthy AI because it already provides the qualities AI systems need: durable memory, expressive retrieval, transactional guarantees, auditing, and safe interfaces for executing real work.
>
> This talk shows how to turn Postgres into a full AI application server & control plane by combining Retrieval Augmented Generation (RAG) and the Model Context Protocol (MCP) directly inside the database. We walk through a practical demo of a Postgres-centric agent that produces a structured technical artifact using RAG and an MCP-style control plane, highlighting how evaluation, retries, and stopping conditions are enforced inside the database.
>
> This talk blends conceptual clarity with practical implementation and includes a live demonstration of Postgres acting as the brain, memory, and control surface for an intelligent and reliable agent.

**Conference:** [Scale23x — March 2026](https://www.socallinuxexpo.org/scale/23x/presentations/postgres-ai-control-plane-building-rag-mcp-workflows-inside-database)
