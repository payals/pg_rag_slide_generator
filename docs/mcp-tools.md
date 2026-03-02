# MCP Tools

## What is MCP?

The Model Context Protocol (MCP) defines a typed interface between an LLM and external systems. In this project, MCP serves as a **safety boundary**: the LLM never sees raw SQL or has direct database access. Every interaction goes through a validated, audited tool call.

## Architecture

The MCP server runs **in-process** via FastMCP's in-memory transport — no network hop, no serialization overhead. The call path is:

```
Orchestrator → MCP Client (singleton) → in-memory transport → FastMCP Server → asyncpg → Postgres
```

`src/mcp_server.py` defines all 15 tools. `src/mcp_client.py` provides the `tool_call()` function that routes calls through the in-memory transport.

## Tool Inventory

### Knowledge (2 tools)

| Tool | Parameters | Returns | Wraps |
|------|-----------|---------|-------|
| `mcp_search_chunks` | `query`, `doc_type?`, `trust_level?`, `tags?`, `top_k=10`, `semantic_weight=0.7`, `lexical_weight=0.3` | Ranked chunks with scores | `fn_hybrid_search` + cross-encoder reranking |
| `mcp_get_chunk` | `chunk_id` | Single chunk with full metadata | Direct query |

### Deck Management (3 tools)

| Tool | Parameters | Returns | Wraps |
|------|-----------|---------|-------|
| `mcp_create_deck` | `topic`, `target_slides?`, `description?`, `tone?`, `audience?`, `bullet_style?` | Deck ID | `fn_create_deck` |
| `mcp_get_deck_state` | `deck_id` | Deck + coverage + health + slides as JSONB | `fn_get_deck_state` |
| `mcp_pick_next_intent` | `deck_id`, `exclude?` | Next intent to generate | `fn_pick_next_intent` |

### Gate Validation (5 tools)

| Tool | Parameters | Returns | Wraps |
|------|-----------|---------|-------|
| `mcp_check_retrieval_quality` | `search_results`, `min_chunks?`, `min_score?` | Pass/fail with chunk count and top score | `fn_check_retrieval_quality` (G1) |
| `mcp_validate_slide_structure` | `slide_spec` | Pass/fail with details | `fn_validate_slide_structure` (G3) |
| `mcp_validate_citations` | `slide_spec`, `min_citations=1` | Pass/fail with invalid IDs | `fn_validate_citations` (G2) |
| `mcp_check_novelty` | `deck_id`, `candidate_text`, `threshold=0.85` | Pass/fail with similarity score | `fn_check_novelty` (G4) |
| `mcp_check_grounding` | `slide_spec`, `threshold=0.3`, `run_id?` | Pass/fail per bullet with scores | `fn_check_grounding` (G2.5) |

### Images (3 tools)

| Tool | Parameters | Returns | Wraps |
|------|-----------|---------|-------|
| `mcp_search_images` | `query`, `filters?`, `top_k=5` | Ranked images with scores | `fn_search_images` |
| `mcp_get_image` | `image_id` | Full image metadata | Direct query |
| `mcp_validate_image` | `image_id` | Validation result (license, attribution, file exists) | Direct validation |

### Commit (1 tool)

| Tool | Parameters | Returns | Wraps |
|------|-----------|---------|-------|
| `mcp_commit_slide` | `deck_id`, `slide_no`, `slide_spec`, `run_id?`, `novelty_passed?`, `novelty_score?`, `grounding_passed?`, `grounding_score?`, `image_id?` | Committed slide ID | `fn_commit_slide` (G5) |

### Reporting (1 tool)

| Tool | Parameters | Returns | Wraps |
|------|-----------|---------|-------|
| `mcp_get_run_report` | `deck_id` | Comprehensive run report JSON | `fn_get_run_report` |

## Why MCP Over Raw SQL

1. **Type safety.** Pydantic models validate every tool input and output. Malformed requests fail before reaching Postgres.

2. **Audit trail.** Gate validation tools automatically log decisions to `gate_log`. Retrieval tools log to `retrieval_log`. The LLM can't bypass logging.

3. **The LLM never sees SQL.** Tool descriptions and parameter names are the LLM's entire interface to the database. This prevents prompt injection into SQL, eliminates SQL syntax errors, and makes the interaction auditable at the tool-call level.

4. **Safety boundary.** Tools enforce invariants that the LLM can't override: citation integrity, format compliance, novelty thresholds. The LLM proposes content; the tools (and Postgres behind them) decide whether it's accepted.
