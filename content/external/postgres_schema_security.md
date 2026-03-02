# Postgres Schema Design and Security for AI Systems

**Source:** Internal project documentation and db/schema.sql implementation
**Type:** Implementation Guide
**Trust Level:** High

---

## Defense-in-Depth: Why Schema Security Matters for AI

When an AI system stores knowledge, makes decisions, and logs everything in a single database, schema security becomes critical. A defense-in-depth approach layers multiple security mechanisms so that no single failure compromises the system. In an AI control plane built on Postgres, this means protecting the database not just from external attackers but from the AI agent itself — preventing it from bypassing validation, accessing data it shouldn't, or corrupting audit trails.

The key insight is that Postgres already provides the primitives needed for defense-in-depth: function-level security attributes, search path isolation, privilege separation, typed function interfaces, and comprehensive audit logging. These are the same mechanisms database engineers use for any production system, applied here to constrain an AI agent.

## SECURITY INVOKER: Functions Run with Caller's Permissions

All SQL functions in this architecture use `SECURITY INVOKER`, which means each function runs with the permissions of the calling role — not elevated superuser privileges. This is the safer default compared to `SECURITY DEFINER`, which would execute with the function owner's (typically higher) permissions.

Why this matters for AI systems:

- The application connects with a limited-privilege role (`slidegen_app`), not a superuser. Even if the AI agent calls `fn_commit_slide`, it only has the permissions granted to `slidegen_app`.
- If an AI agent managed to inject unexpected function calls, those calls would still be constrained to the caller's privilege level.
- `SECURITY INVOKER` prevents privilege escalation through function calls. It has always been the default for PostgreSQL functions; Postgres 15 added syntax to set it declaratively at the schema level.

Example from the schema:

```sql
CREATE OR REPLACE FUNCTION fn_hybrid_search(...)
RETURNS TABLE(...)
AS $$ ... $$
LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE
   SET search_path = public;
```

Every function in the system — `fn_hybrid_search`, `fn_check_novelty`, `fn_validate_slide_structure`, `fn_commit_slide`, `fn_log_gate`, and all others — consistently uses `SECURITY INVOKER`.

## SET search_path: Preventing Schema Hijacking

Every function explicitly sets `SET search_path = public`. This prevents a class of attacks called search path hijacking, where an attacker creates a malicious function in a schema that appears earlier in the search path, causing the legitimate function to call the attacker's version instead.

Without explicit search path settings, a function like `fn_commit_slide` could inadvertently call a hijacked version of `fn_validate_citations` if someone placed a malicious function in a higher-priority schema. By setting `search_path = public` on every function, the system ensures that all function calls resolve to the intended schema.

This is especially important in AI systems where:

- Multiple extensions (pgvector, pg_trgm, pgcrypto, unaccent) add functions to the search path.
- Functions call other functions in chains (e.g., `fn_commit_slide` calls `fn_validate_slide_structure` and `fn_validate_citations` internally).
- The database is the control plane — a hijacked function could silently approve invalid AI outputs.

## REVOKE PUBLIC: Principle of Least Privilege

The schema includes a production security section that revokes default public access to all functions and grants access only to the application role:

```sql
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

CREATE ROLE slidegen_app LOGIN PASSWORD '...';
GRANT USAGE ON SCHEMA public TO slidegen_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON doc, chunk, deck, slide TO slidegen_app;
GRANT SELECT, INSERT ON retrieval_log, gate_log TO slidegen_app;

GRANT EXECUTE ON FUNCTION fn_hybrid_search TO slidegen_app;
GRANT EXECUTE ON FUNCTION fn_check_novelty TO slidegen_app;
GRANT EXECUTE ON FUNCTION fn_validate_slide_structure TO slidegen_app;
GRANT EXECUTE ON FUNCTION fn_validate_citations TO slidegen_app;
GRANT EXECUTE ON FUNCTION fn_commit_slide TO slidegen_app;
GRANT EXECUTE ON FUNCTION fn_log_retrieval TO slidegen_app;
GRANT EXECUTE ON FUNCTION fn_log_gate TO slidegen_app;
```

Key design decisions:

- **Append-only logs:** `retrieval_log` and `gate_log` are granted `SELECT, INSERT` only — no `UPDATE` or `DELETE`. The AI agent cannot tamper with its own audit trail.
- **Table grants for operational use only:** The app role has `SELECT, INSERT, UPDATE, DELETE` on core tables (`doc`, `chunk`, `deck`, `slide`), but the orchestrator never uses these for AI-generated content. All slide creation, search, and validation flow through typed MCP functions (`fn_commit_slide`, `fn_hybrid_search`, etc.). The direct grants exist for run-lifecycle housekeeping (e.g., `generation_run` status updates) and migration tooling — not for the AI pipeline itself.
- **Explicit function grants:** Rather than granting execute on all functions, each function is individually granted. This prevents newly added functions from being automatically accessible.

## Typed Functions as the Security Boundary

Instead of allowing raw SQL from the AI agent, all database interactions go through typed PL/pgSQL functions exposed via MCP (Model Context Protocol) tools. This creates a security boundary where:

1. **The AI agent never sees database credentials.** MCP tools are typed wrappers — `mcp_search_chunks(query, topK)` instead of `SELECT * FROM chunk WHERE ...`.
2. **Input validation happens in SQL.** Functions like `fn_validate_slide_structure` perform type-aware CASE dispatch to validate bullet counts, word limits, code line counts, and diagram structure — all enforced in the database, not in application code.
3. **No dynamic SQL.** All queries use parameterized PL/pgSQL (`$1`, `$2`), eliminating SQL injection risk even if the AI generates adversarial inputs.
4. **Gate re-validation at commit time.** `fn_commit_slide` re-runs G2 (citation integrity) and G3 (format validation) at INSERT time, regardless of what the orchestrator claims it already checked. This "trust but verify" pattern means a bug in the Python orchestrator cannot bypass database-enforced constraints.

The 15 typed functions form the complete API surface:

| Category | Functions |
|----------|-----------|
| Search | `fn_hybrid_search`, `fn_search_images` |
| Validation | `fn_validate_slide_structure`, `fn_validate_citations`, `fn_check_grounding`, `fn_check_novelty` |
| State | `fn_pick_next_intent`, `fn_create_deck`, `fn_get_deck_state`, `fn_get_run_report` |
| Commit | `fn_commit_slide` |
| Logging | `fn_log_retrieval`, `fn_log_gate` |
| Triggers | `update_chunk_tsv`, `update_slide_content_text`, `fn_validate_type_config`, `fn_set_updated_at` |

## Audit Tables: Immutable Evidence of AI Behavior

The audit layer consists of three tables that create an immutable record of every decision the AI system makes:

### gate_log

Every gate decision — pass or fail — is recorded with full context:

```sql
CREATE TABLE gate_log (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id     UUID REFERENCES generation_run(run_id),
    gate_name  TEXT NOT NULL,
    decision   gate_decision NOT NULL,
    score      FLOAT,
    threshold  FLOAT,
    reason     TEXT,
    payload    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

A CHECK constraint restricts `gate_name` to known values (`g1_retrieval`, `g2_citations`, `g2_5_grounding`, `g3_format`, `g4_novelty`, `g5_commit`), preventing the AI from logging to fabricated gate names.

### retrieval_log

Every search operation is logged with the query, candidate count, selected count, and latency:

```sql
CREATE TABLE retrieval_log (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id     UUID REFERENCES generation_run(run_id),
    query_text TEXT NOT NULL,
    candidates INT,
    selected   INT,
    latency_ms FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### generation_run

Run-level metrics track cost, token usage, and status for each generation attempt:

```sql
CREATE TABLE generation_run (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deck_id         UUID REFERENCES deck(deck_id),
    status          run_status NOT NULL DEFAULT 'running',
    slides_generated INT DEFAULT 0,
    slides_failed    INT DEFAULT 0,
    total_retries    INT DEFAULT 0,
    llm_calls        INT DEFAULT 0,
    prompt_tokens    INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    embedding_tokens  INT DEFAULT 0,
    estimated_cost_usd FLOAT DEFAULT 0,
    error            TEXT,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ
);
```

Together these tables ensure that AI behavior is observable, auditable, and non-repudiable. The append-only permission model (`INSERT` only, no `UPDATE` or `DELETE` for the app role) means the AI agent cannot cover its tracks.

## Constraint-Driven Design Patterns

Beyond security attributes, the schema uses several Postgres constraint mechanisms to enforce AI system invariants:

### Triggers for Contract Validation

The `fn_validate_type_config` trigger fires on `INSERT` or `UPDATE` to `slide_type_config` and validates that all keys in the `content_fields` JSONB appear in the `html_fragment` template string. This prevents broken rendering contracts — if someone adds a content field that the template doesn't reference, the INSERT is rejected at the database level.

### Partial Unique Indexes for Configuration Integrity

Prompt templates use a partial unique index to enforce exactly one active prompt per purpose:

```sql
CREATE UNIQUE INDEX idx_prompt_template_active 
ON prompt_template (purpose) 
WHERE is_active = true;
```

This means the database itself prevents configuration conflicts — you cannot accidentally activate two prompts for the same purpose, regardless of how the application code behaves.

### Enum Types for Domain Integrity

Eight custom enums (`doc_type`, `image_style`, `trust_level`, `gate_decision`, `slide_intent`, `slide_type`, `deck_status`, `run_status`) enforce valid values at the type level. The AI agent cannot commit a slide with an invalid intent or set a deck to an undefined status.

### Foreign Key Cascades for Referential Integrity

The schema uses `ON DELETE CASCADE` for document-to-chunk relationships, ensuring that deleting a document automatically removes its chunks and preserves referential integrity. Slides reference `image_asset` with a nullable foreign key, allowing optional images without orphaned references.

## Row-Level Security Considerations

While Row-Level Security (RLS) policies are not currently enabled in this single-tenant demo, the architecture is designed to support them for multi-tenant deployments:

- The `deck` table could have RLS policies restricting access to decks owned by the current user.
- The `slide` table inherits deck-level access through its `deck_id` foreign key.
- The `gate_log` and `retrieval_log` tables could be restricted through their `run_id` relationship to `generation_run`, which links back to `deck`.
- All functions already use `SECURITY INVOKER`, which is a prerequisite for RLS policies to work correctly — `SECURITY DEFINER` functions bypass RLS by default.

The Supabase best practices for AI agents recommend keeping embeddings in Postgres with pgvector specifically because it enables row-level security on vector data — something external vector databases cannot provide. When embeddings, metadata, and access policies live in the same database, authorization decisions can be made atomically within the same transaction as retrieval.

## Summary: The Five Layers of Schema Security

The defense-in-depth approach for this AI control plane consists of five reinforcing layers:

1. **SECURITY INVOKER** — Functions execute with caller privileges, not elevated permissions.
2. **SET search_path** — Every function pins its schema resolution to prevent hijacking.
3. **REVOKE PUBLIC / GRANT minimal** — Only the app role can execute functions; logs are append-only.
4. **Typed functions via MCP** — The AI never executes raw SQL; all access goes through validated, parameterized functions.
5. **Audit tables** — Every decision is logged immutably, with CHECK constraints on gate names and append-only permissions.

These five layers ensure that even if one mechanism fails, the others prevent unauthorized access or data corruption. The database is not just storing data — it is actively enforcing the security boundaries that make the AI system trustworthy.

---

*Compiled: 2026-02-23*
