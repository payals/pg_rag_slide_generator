"""
All SVG image data configurations for the Scale23x presentation.

Each entry maps an image name (matching the JSON sidecar filename stem)
to a dict with:
  - category: "diagram" | "chart" | "code" | "decorative"
  - template: template function name within the category module
  - config: kwargs dict passed to the template function
  - output_format: "svg" (default) or "png" (requires cairosvg)
"""

from scripts.svg_lib.common import Palette

# ---------------------------------------------------------------------------
# Category constants for dispatcher
# ---------------------------------------------------------------------------
DIAGRAM = "diagram"
CHART = "chart"
CODE = "code"
DECORATIVE = "decorative"


# ---------------------------------------------------------------------------
# All 45 SVG image definitions
# ---------------------------------------------------------------------------

IMAGE_DEFS: dict[str, dict] = {

    # ===================================================================
    # GROUP 2: Technical Diagrams (18 images)
    # ===================================================================

    "architecture_01_system_diagram": {
        "category": DIAGRAM,
        "template": "box_and_arrow",
        "config": {
            "title": "System Architecture",
            "components": [
                {"label": "PostgreSQL", "sublabel": "pgvector · pg_trgm · functions · gates · logs", "color": Palette.PG_BLUE},
                {"label": "Ingestion Pipeline", "sublabel": "embed & store", "color": Palette.TEAL},
                {"label": "LLM (Claude/GPT)", "sublabel": "generation", "color": Palette.PURPLE},
                {"label": "MCP Server", "sublabel": "typed tools", "color": Palette.BLUE},
                {"label": "Renderer", "sublabel": "reveal.js", "color": Palette.GREEN},
            ],
        },
    },

    "architecture_03_isometric_platforms": {
        "category": DIAGRAM,
        "template": "layered_boxes",
        "config": {
            "title": "Architecture Layers",
            "layers": [
                {"label": "Presentation — reveal.js renderer"},
                {"label": "Control Plane — gates, validation, audit"},
                {"label": "MCP Interface — typed tool boundary"},
                {"label": "AI Engine — LLM generation & retrieval"},
                {"label": "Data Foundation — PostgreSQL + extensions"},
            ],
        },
    },

    "thesis_01_deterministic_split": {
        "category": DIAGRAM,
        "template": "split_comparison",
        "config": {
            "title": "Deterministic vs Non-Deterministic",
            "left": {
                "title": "PostgreSQL (Deterministic)",
                "color": Palette.BLUE,
                "items": [
                    "ACID transactions",
                    "Repeatable queries",
                    "Auditable state",
                    "Schema-enforced types",
                    "Version-controlled data",
                ],
            },
            "right": {
                "title": "LLM (Non-Deterministic)",
                "color": Palette.PURPLE,
                "items": [
                    "Temperature-dependent output",
                    "Hallucination risk",
                    "Token-limited context",
                    "No built-in memory",
                    "Probabilistic responses",
                ],
            },
        },
    },

    "thesis_03_concentric_rings": {
        "category": DIAGRAM,
        "template": "concentric_rings",
        "config": {
            "title": "Control Plane Architecture",
            "rings": [
                {"label": "Data · pgvector · pg_trgm"},
                {"label": "Gates · Functions · State"},
                {"label": "🐘 PostgreSQL = The Control Plane"},
                {"label": "FastMCP (Thin Wrapper)"},
                {"label": "LLM (Only Thing Outside Postgres)"},
            ],
        },
    },

    "capabilities_01_extension_grid": {
        "category": DIAGRAM,
        "template": "card_grid",
        "config": {
            "title": "PostgreSQL Extensions for AI",
            "cols": 3,
            "cards": [
                {"title": "pgvector", "body": ["Vector similarity search", "cosine, L2, inner product"], "color": Palette.BLUE},
                {"title": "pg_trgm", "body": ["Trigram fuzzy matching", "similarity() + GIN index"], "color": Palette.TEAL},
                {"title": "tsvector", "body": ["Full-text search", "ts_rank + tsquery"], "color": Palette.GREEN},
                {"title": "PL/pgSQL", "body": ["Procedural functions", "gates, validation, logic"], "color": Palette.PURPLE},
                {"title": "pg_stat", "body": ["Query statistics", "Execution time tracking"], "color": Palette.ORANGE},
                {"title": "JSONB", "body": ["Structured JSON storage", "GIN-indexed queries"], "color": Palette.CYAN},
            ],
        },
    },

    "capabilities_02_layer_cake": {
        "category": DIAGRAM,
        "template": "layer_stack",
        "config": {
            "title": "PostgreSQL Capability Stack",
            "layers": [
                {"label": "Security — REVOKE, SECURITY INVOKER, search_path"},
                {"label": "Observability — pg_stat, views, gate_log"},
                {"label": "AI/ML — pgvector, embeddings, hybrid search"},
                {"label": "Data Processing — JSONB, full-text, trigram"},
                {"label": "Foundation — ACID, extensions, typed functions"},
            ],
        },
    },

    "rag_in_postgres_01_hybrid_search": {
        "category": DIAGRAM,
        "template": "merge_flow",
        "config": {
            "title": "Hybrid Search Pipeline",
            "inputs": [
                {"label": "Semantic Search (pgvector)", "color": Palette.BLUE},
                {"label": "Trigram Search (pg_trgm)", "color": Palette.GREEN},
                {"label": "Full-Text Search (tsvector)", "color": Palette.ORANGE},
            ],
            "merger": "RRF Fusion",
            "output": "Ranked Results",
        },
    },

    "rag_in_postgres_04_latency_comparison": {
        "category": DIAGRAM,
        "template": "split_comparison",
        "config": {
            "title": "RAG Latency: External vs In-DB",
            "left": {
                "title": "External RAG Stack",
                "color": Palette.RED,
                "items": [
                    "Network call → Vector DB",
                    "Network call → Reranker API",
                    "Network call → LLM API",
                    "3 round-trips minimum",
                    "~500-2000ms total",
                ],
            },
            "right": {
                "title": "Postgres RAG (In-DB)",
                "color": Palette.GREEN,
                "items": [
                    "1 SQL query: hybrid search",
                    "Built-in RRF ranking",
                    "Co-located with data",
                    "1 round-trip to DB",
                    "~50-200ms total",
                ],
            },
        },
    },

    "what_is_mcp_01_layered_gateway": {
        "category": DIAGRAM,
        "template": "layer_stack",
        "config": {
            "title": "MCP as Gateway Layer",
            "layers": [
                {"label": "LLM Host — Claude, GPT, etc."},
                {"label": "MCP Gateway — JSON-RPC protocol"},
                {"label": "Data Sources — PostgreSQL, APIs, Files"},
            ],
        },
    },

    "what_is_mcp_04_usb_adapter": {
        "category": DIAGRAM,
        "template": "hub_spoke_horizontal",
        "config": {
            "title": "MCP: Universal Adapter Pattern",
            "hub": {"label": "MCP Protocol", "color": Palette.PURPLE},
            "left": [
                {"label": "Claude", "color": Palette.BLUE},
                {"label": "GPT-4", "color": Palette.GREEN},
                {"label": "Gemini", "color": Palette.ORANGE},
            ],
            "right": [
                {"label": "PostgreSQL", "color": Palette.PG_BLUE},
                {"label": "REST APIs", "color": Palette.TEAL},
                {"label": "File System", "color": Palette.CYAN},
            ],
        },
    },

    "mcp_tools_01_tool_registry": {
        "category": DIAGRAM,
        "template": "card_grid",
        "config": {
            "title": "MCP Tool Registry",
            "cols": 2,
            "cards": [
                {"title": "search_chunks", "body": ["Hybrid search over knowledge base", "Returns ranked chunks with scores"], "color": Palette.BLUE},
                {"title": "validate_slide", "body": ["Run all gates on a slide draft", "Returns pass/fail with reasons"], "color": Palette.GREEN},
                {"title": "check_novelty", "body": ["Ensure no content repetition", "Compares against existing slides"], "color": Palette.PURPLE},
                {"title": "commit_slide", "body": ["Persist validated slide to deck", "Atomic insert with gate logging"], "color": Palette.TEAL},
            ],
        },
    },

    "mcp_tools_02_safe_vs_dangerous": {
        "category": DIAGRAM,
        "template": "split_comparison",
        "config": {
            "title": "Safe vs Dangerous: MCP Boundary",
            "left": {
                "title": "DANGEROUS: Raw SQL",
                "color": Palette.RED,
                "items": [
                    "LLM generates SQL directly",
                    "SQL injection risk",
                    "No schema validation",
                    "Unrestricted access",
                    "No audit trail",
                ],
            },
            "right": {
                "title": "SAFE: Typed MCP Tools",
                "color": Palette.GREEN,
                "items": [
                    "Predefined function signatures",
                    "Input validation (Pydantic)",
                    "SECURITY INVOKER functions",
                    "Least-privilege access",
                    "Full audit logging",
                ],
            },
        },
    },

    "mcp_tools_03_mapping_diagram": {
        "category": DIAGRAM,
        "template": "two_col_mapping",
        "config": {
            "title": "MCP Tools → PostgreSQL Functions",
            "left_header": "MCP Tools",
            "right_header": "PG Functions",
            "left": [
                {"label": "search_chunks()"},
                {"label": "validate_slide()"},
                {"label": "check_novelty()"},
                {"label": "commit_slide()"},
            ],
            "right": [
                {"label": "fn_hybrid_search()", "locked": True},
                {"label": "fn_validate_slide()", "locked": True},
                {"label": "fn_check_novelty()", "locked": True},
                {"label": "fn_commit_slide()", "locked": True},
            ],
        },
    },

    "gates_03_assembly_qc": {
        "category": DIAGRAM,
        "template": "horizontal_flow",
        "config": {
            "title": "Quality Gate Assembly Line",
            "steps": [
                {"label": "G1: Retrieval", "sublabel": "Chunk relevance"},
                {"label": "G2: Citations", "sublabel": "Source verification"},
                {"label": "G3: Format", "sublabel": "Structure check"},
                {"label": "G4: Novelty", "sublabel": "No repetition"},
            ],
        },
    },

    "schema_security_01_defense_layers": {
        "category": DIAGRAM,
        "template": "nested_rects",
        "config": {
            "title": "Defense-in-Depth: Schema Security",
            "labels": [
                "REVOKE public schema access",
                "SECURITY INVOKER functions",
                "SET search_path = pg_catalog, public",
                "Typed function interfaces only",
            ],
        },
    },

    "what_is_rag_02_before_after": {
        "category": DIAGRAM,
        "template": "split_comparison",
        "config": {
            "title": "Before & After: RAG Effect",
            "left": {
                "title": "Without RAG",
                "color": Palette.RED,
                "items": [
                    "LLM uses training data only",
                    "Stale knowledge cutoff",
                    "No source citations",
                    "Hallucination risk HIGH",
                    "Generic responses",
                ],
            },
            "right": {
                "title": "With RAG",
                "color": Palette.GREEN,
                "items": [
                    "LLM augmented with fresh docs",
                    "Real-time knowledge retrieval",
                    "Every claim cited to source",
                    "Hallucination risk LOW",
                    "Domain-specific accuracy",
                ],
            },
        },
    },

    "observability_04_cost_comparison": {
        "category": DIAGRAM,
        "template": "split_comparison",
        "config": {
            "title": "Observability: Expensive vs Simple",
            "left": {
                "title": "Expensive Stack",
                "color": Palette.RED,
                "items": [
                    "DataDog ($$$)",
                    "LangSmith ($$$)",
                    "Custom dashboards",
                    "Complex integrations",
                    "Vendor lock-in",
                ],
            },
            "right": {
                "title": "SQL Views (Free)",
                "color": Palette.GREEN,
                "items": [
                    "v_deck_coverage",
                    "v_deck_health",
                    "v_gate_failures",
                    "pg_stat_statements",
                    "Zero additional cost",
                ],
            },
        },
    },

    "takeaways_01_four_cards": {
        "category": DIAGRAM,
        "template": "card_grid",
        "config": {
            "title": "Key Takeaways",
            "cols": 2,
            "cards": [
                {"title": "DB = Control Plane", "body": ["PostgreSQL as the", "deterministic backbone"], "color": Palette.BLUE},
                {"title": "RAG = R+S+G+P", "body": ["Retrieve, Search,", "Ground, Provenance"], "color": Palette.GREEN},
                {"title": "MCP = Safety Layer", "body": ["Typed tools, no raw SQL", "Least-privilege access"], "color": Palette.PURPLE},
                {"title": "PG = More Than DB", "body": ["Extensions make it an", "AI application server"], "color": Palette.TEAL},
            ],
        },
    },

    # ===================================================================
    # GROUP 3: Charts & Infographics (6 images)
    # ===================================================================

    "rag_in_postgres_03_venn_hybrid": {
        "category": CHART,
        "template": "venn_3",
        "config": {
            "title": "Hybrid Search: Three Methods Combined",
            "circles": [
                {"color": Palette.BLUE, "label": "Semantic (pgvector)"},
                {"color": Palette.GREEN, "label": "Full-Text (tsvector)"},
                {"color": Palette.ORANGE, "label": "Fuzzy (pg_trgm)"},
            ],
            "center": "Hybrid RRF",
        },
    },

    "schema_security_04_permissions_matrix": {
        "category": CHART,
        "template": "matrix_grid",
        "config": {
            "title": "Role Permissions Matrix",
            "cols": ["SELECT", "INSERT", "UPDATE", "DELETE", "EXECUTE"],
            "rows": ["app_readonly", "app_writer", "app_admin"],
            "data": [
                [True, False, False, False, True],
                [True, True, True, False, True],
                [True, True, True, True, True],
            ],
        },
    },

    "takeaways_02_pyramid": {
        "category": CHART,
        "template": "pyramid",
        "config": {
            "title": "Architecture Pyramid",
            "levels": [
                {"label": "Gates & Observability", "sublabel": "validation · audit logs · SQL views"},
                {"label": "MCP Safety Boundary", "sublabel": "typed tools · no raw SQL · FastMCP"},
                {"label": "RAG Pipeline", "sublabel": "hybrid search · citations · pgvector"},
                {"label": "🐘 PostgreSQL = The Control Plane", "sublabel": "ACID · extensible · everything runs here"},
            ],
        },
    },

    "takeaways_03_mind_map": {
        "category": CHART,
        "template": "mind_map",
        "config": {
            "title": "",
            "center": "PG as AI Control Plane",
            "branches": [
                {"label": "Control", "children": ["Deterministic", "Auditable", "Gates"]},
                {"label": "RAG", "children": ["Hybrid Search", "Citations", "Reranking"]},
                {"label": "MCP Safety", "children": ["Typed Tools", "No Raw SQL", "FastMCP"]},
                {"label": "Extensible", "children": ["pgvector", "pg_trgm", "SQL Views"]},
            ],
        },
    },

    "takeaways_04_checklist": {
        "category": CHART,
        "template": "checklist",
        "config": {
            "title": "Your Postgres AI Checklist",
            "items": [
                "Use PostgreSQL as your control plane, not just storage",
                "Implement hybrid search: semantic + full-text + fuzzy",
                "Add MCP typed tools — never expose raw SQL to LLMs",
                "Build quality gates that log everything to the database",
            ],
        },
    },

    "what_we_built_04_stats_infographic": {
        "category": CHART,
        "template": "stat_cards",
        "config": {
            "title": "What We Built: By the Numbers",
            "cols": 3,
            "stats": [
                {"value": "15", "label": "Slides Generated", "subtitle": "RAG-powered content", "color": Palette.BLUE},
                {"value": "6", "label": "Quality Gates", "subtitle": "G1–G5 + grounding", "color": Palette.GREEN},
                {"value": "3", "label": "Search Methods", "subtitle": "semantic · full-text · fuzzy", "color": Palette.TEAL},
                {"value": "100%", "label": "Auditable", "subtitle": "every decision logged", "color": Palette.PURPLE},
                {"value": "0", "label": "Raw SQL Exposed", "subtitle": "typed MCP tools only", "color": Palette.RED},
                {"value": "1", "label": "Database (PG)", "subtitle": "single source of truth", "color": Palette.PG_BLUE},
            ],
        },
    },

    # ===================================================================
    # GROUP 4: Code / Screenshot Style (8 images)
    # ===================================================================

    "capabilities_04_sql_snippet": {
        "category": CODE,
        "template": "code_editor",
        "config": {
            "title": "",
            "filename": "hybrid_search.sql",
            "code": [
                "SELECT c.chunk_id, c.body,",
                "  1 - (c.embedding <=> $1::vector)   AS sem_score,",
                "  similarity(c.body, $2)               AS trgm_score,",
                "  ts_rank(c.fts, plainto_tsquery($2))  AS fts_score,",
                "  -- Reciprocal Rank Fusion",
                "  (1.0/(60 + rank_sem) +",
                "   1.0/(60 + rank_trgm) +",
                "   1.0/(60 + rank_fts))               AS rrf_score",
                "FROM chunk c",
                "ORDER BY rrf_score DESC",
                "LIMIT $3;",
            ],
            "annotations": [
                {"line": 2, "text": "pgvector", "color": Palette.BLUE},
                {"line": 3, "text": "pg_trgm", "color": Palette.GREEN},
                {"line": 4, "text": "tsvector", "color": Palette.ORANGE},
                {"line": 6, "text": "RRF Fusion", "color": Palette.PURPLE},
            ],
        },
    },

    "rag_in_postgres_02_sql_visualization": {
        "category": CODE,
        "template": "code_editor",
        "config": {
            "title": "",
            "filename": "hybrid_search_order.sql",
            "code": [
                "-- Hybrid Search: ORDER BY with RRF",
                "SELECT chunk_id, body, section_header,",
                "  -- Semantic similarity (pgvector)",
                "  1 - (embedding <=> query_vec) AS semantic,",
                "",
                "  -- Trigram fuzzy match (pg_trgm)",
                "  similarity(body, query_text)  AS trigram,",
                "",
                "  -- Full-text relevance (tsvector)",
                "  ts_rank(fts, to_tsquery(query_text)) AS fulltext",
                "",
                "FROM chunk",
                "WHERE embedding <=> query_vec < 0.8",
                "ORDER BY rrf_score DESC",
                "LIMIT 10;",
            ],
            "annotations": [
                {"line": 4, "text": "cosine distance", "color": Palette.BLUE},
                {"line": 7, "text": "fuzzy matching", "color": Palette.GREEN},
                {"line": 10, "text": "BM25 ranking", "color": Palette.ORANGE},
            ],
        },
    },

    "mcp_tools_04_json_to_sql": {
        "category": CODE,
        "template": "code_editor_split",
        "config": {
            "title": "MCP Tool → PostgreSQL Function",
            "left_title": "MCP Tool Schema (JSON)",
            "right_title": "PostgreSQL Function",
            "left_code": [
                '{',
                '  "name": "search_chunks",',
                '  "description": "Hybrid search",',
                '  "inputSchema": {',
                '    "type": "object",',
                '    "properties": {',
                '      "query": {',
                '        "type": "string"',
                '      },',
                '      "limit": {',
                '        "type": "integer",',
                '        "default": 10',
                '      }',
                '    }',
                '  }',
                '}',
            ],
            "right_code": [
                "CREATE FUNCTION",
                "  fn_hybrid_search(",
                "    p_query    TEXT,",
                "    p_limit    INTEGER",
                "      DEFAULT 10",
                "  )",
                "RETURNS TABLE (",
                "  chunk_id  UUID,",
                "  body      TEXT,",
                "  score     FLOAT",
                ")",
                "LANGUAGE plpgsql",
                "SECURITY INVOKER",
                "SET search_path =",
                "  pg_catalog, public",
                "AS $$ ... $$;",
            ],
        },
    },

    "schema_security_03_function_code": {
        "category": CODE,
        "template": "code_editor",
        "config": {
            "title": "",
            "filename": "secure_function.sql",
            "code": [
                "CREATE FUNCTION fn_search_chunks(",
                "  p_query       TEXT,",
                "  p_embedding   VECTOR(1536),",
                "  p_limit       INTEGER DEFAULT 10",
                ")",
                "RETURNS TABLE (",
                "  chunk_id  UUID,",
                "  body      TEXT,",
                "  score     FLOAT",
                ")",
                "LANGUAGE plpgsql",
                "SECURITY INVOKER    -- runs as caller",
                "SET search_path = pg_catalog, public",
                "AS $$",
                "BEGIN",
                "  RETURN QUERY ...",
                "END;",
                "$$;",
            ],
            "annotations": [
                {"line": 12, "text": "SECURITY INVOKER", "color": Palette.GREEN},
                {"line": 13, "text": "search_path locked", "color": Palette.YELLOW},
                {"line": 6, "text": "typed output", "color": Palette.BLUE},
            ],
        },
    },

    "gates_04_gate_log_table": {
        "category": CODE,
        "template": "db_table",
        "config": {
            "title": "gate_log Table",
            "table_name": "gate_log",
            "columns": ["gate_name", "slide_no", "passed", "score", "reason"],
            "rows": [
                {"cells": ["G1_RETRIEVAL", "1", {"value": "✓", "color": Palette.GREEN}, "0.92", "5 relevant chunks"], "row_color": Palette.GREEN},
                {"cells": ["G2_CITATIONS", "1", {"value": "✓", "color": Palette.GREEN}, "1.00", "all claims cited"]},
                {"cells": ["G3_FORMAT", "1", {"value": "✓", "color": Palette.GREEN}, "0.95", "5 bullets, good length"], "row_color": Palette.GREEN},
                {"cells": ["G4_NOVELTY", "1", {"value": "✗", "color": Palette.RED}, "0.35", "too similar to slide 3"], "row_color": Palette.RED},
                {"cells": ["G1_RETRIEVAL", "2", {"value": "✓", "color": Palette.GREEN}, "0.88", "4 relevant chunks"]},
                {"cells": ["G2_CITATIONS", "2", {"value": "✓", "color": Palette.GREEN}, "0.90", "citations verified"], "row_color": Palette.GREEN},
                {"cells": ["G3_FORMAT", "2", {"value": "✗", "color": Palette.RED}, "0.40", "only 2 bullets"], "row_color": Palette.RED},
                {"cells": ["G4_NOVELTY", "2", {"value": "✓", "color": Palette.GREEN}, "0.95", "unique content"]},
            ],
        },
    },

    "observability_01_dashboard": {
        "category": CODE,
        "template": "multi_panel",
        "config": {
            "title": "SQL-Powered Monitoring Dashboard",
            "layout": "2x2",
            "panels": [
                {
                    "title": "v_deck_coverage",
                    "color": Palette.BLUE,
                    "content": [
                        "intent_no | covered | slide_no",
                        "1         | true    | 1",
                        "2         | true    | 2",
                        "...       | ...     | ...",
                        "14        | true    | 14",
                        "━━━━━━━━━━━━━━━━━━━━━",
                        "Coverage: 14/14 (100%)",
                    ],
                },
                {
                    "title": "v_deck_health",
                    "color": Palette.GREEN,
                    "content": [
                        "slide | retries | novelty",
                        "1     | 0       | 0.95",
                        "2     | 1       | 0.88",
                        "3     | 0       | 0.92",
                        "4     | 2       | ⚠ 0.45",
                        "━━━━━━━━━━━━━━━━━━━━",
                        "Avg retries: 0.7",
                    ],
                },
                {
                    "title": "v_gate_failures",
                    "color": Palette.PURPLE,
                    "content": [
                        "gate    | fails | retry_pct",
                        "G1_RET  | 2     | 14%",
                        "G2_CITE | 3     | 21%",
                        "G3_FMT  | 1     | 7%",
                        "G4_NOV  | 4     | 28%",
                        "━━━━━━━━━━━━━━━━━━━━━",
                        "Total failures: 10",
                    ],
                },
                {
                    "title": "pg_stat_statements",
                    "color": Palette.TEAL,
                    "content": [
                        "query             | calls | ms",
                        "fn_hybrid_search  | 42    | 12",
                        "fn_commit_slide   | 14    | 8",
                        "fn_check_novelty  | 18    | 15",
                        "fn_validate_slide | 14    | 6",
                        "━━━━━━━━━━━━━━━━━━━━━━",
                        "Total: 88 calls",
                    ],
                },
            ],
        },
    },

    "observability_03_sql_query_result": {
        "category": CODE,
        "template": "multi_panel",
        "config": {
            "title": "SQL Query \u2192 Color-Coded Results",
            "layout": "3x1",
            "panels": [
                {
                    "title": "Query",
                    "color": Palette.BLUE,
                    "content": [
                        "SELECT gate_name,",
                        "  COUNT(*) FILTER",
                        "    (WHERE passed) AS pass,",
                        "  COUNT(*) FILTER",
                        "    (WHERE NOT passed) AS fail",
                        "FROM gate_log",
                        "GROUP BY gate_name;",
                    ],
                },
                {
                    "title": "Results",
                    "color": Palette.GREEN,
                    "content": [
                        "gate     | pass | fail",
                        "G1_RET   |  12  |  2",
                        "G2_CITE  |  11  |  3",
                        "G3_FMT   |  13  |  1",
                        "G4_NOV   |  10  |  4",
                    ],
                },
                {
                    "title": "Insight",
                    "color": Palette.PURPLE,
                    "content": [
                        "G4 Novelty gate has",
                        "highest failure rate.",
                        "",
                        "Action: Improve novelty",
                        "prompt or lower threshold.",
                    ],
                },
            ],
        },
    },

    "what_we_built_02_workspace_screenshot": {
        "category": CODE,
        "template": "multi_panel",
        "config": {
            "title": "Development Workspace",
            "layout": "3x1",
            "panels": [
                {
                    "title": "Terminal (orchestrator)",
                    "color": Palette.GREEN,
                    "content": [
                        "$ python -m src.orchestrator",
                        "  --topic 'Postgres for AI'",
                        "  --slides 14",
                        "",
                        "Slide 1/14: Generating...",
                        "  G1 PASS (0.92)",
                        "  G2 PASS (1.00)",
                        "  G3 PASS (0.95)",
                        "  G4 PASS (0.88)",
                        "  COMMITTED slide 1",
                        "",
                        "Slide 2/14: Generating...",
                    ],
                },
                {
                    "title": "psql (gate_log)",
                    "color": Palette.BLUE,
                    "content": [
                        "scale23x=# SELECT * FROM",
                        "  v_deck_health;",
                        "",
                        " slide | retries | novelty",
                        " 1     | 0       | 0.95",
                        " 2     | 0       | 0.91",
                        " 3     | 1       | 0.88",
                        "",
                        "(3 rows)",
                    ],
                },
                {
                    "title": "Browser (slides)",
                    "color": Palette.PURPLE,
                    "content": [
                        "┌─────────────────────┐",
                        "│  PostgreSQL as the   │",
                        "│  AI Control Plane    │",
                        "│                      │",
                        "│  • Deterministic     │",
                        "│  • Auditable         │",
                        "│  • Extensible        │",
                        "│                      │",
                        "│  slide 3 of 14       │",
                        "└─────────────────────┘",
                    ],
                },
            ],
        },
    },

    # ===================================================================
    # GROUP 5: Decorative / Abstract (8 images)
    # ===================================================================

    "divider_01_why_postgres": {
        "category": DECORATIVE,
        "template": "gradient_elephant_spotlight",
        "config": {
            "title": "Why PostgreSQL?",
            "subtitle": "The elephant in the room",
        },
    },

    "divider_02_the_architecture": {
        "category": DECORATIVE,
        "template": "blueprint_circuit",
        "config": {
            "title": "The Architecture",
            "subtitle": "How the pieces fit together",
        },
    },

    "divider_03_rag_mcp_deep_dive": {
        "category": DECORATIVE,
        "template": "layered_waves",
        "config": {
            "title": "RAG & MCP Deep Dive",
            "subtitle": "Under the hood",
        },
    },

    "divider_04_control_observability": {
        "category": DECORATIVE,
        "template": "dashboard_shapes",
        "config": {
            "title": "Control & Observability",
            "subtitle": "Making the invisible visible",
        },
    },

    "divider_05_the_demo": {
        "category": DECORATIVE,
        "template": "geometric_stage",
        "config": {
            "title": "The Demo",
            "subtitle": "Live from PostgreSQL",
        },
    },

    "capabilities_03_toolbox": {
        "category": DECORATIVE,
        "template": "toolbox",
        "config": {
            "title": "PostgreSQL Toolbox",
            "tools": [
                {"label": "pgvector"},
                {"label": "pg_trgm"},
                {"label": "tsvector"},
                {"label": "PL/pgSQL"},
                {"label": "JSONB"},
                {"label": "pg_stat"},
            ],
        },
    },

    "observability_02_magnifying_glass": {
        "category": DECORATIVE,
        "template": "magnifying_glass",
        "config": {
            "title": "SQL-Powered Observability",
        },
    },

    "schema_security_02_castle_fortress": {
        "category": DECORATIVE,
        "template": "castle_fortress",
        "config": {
            "title": "Schema Security: Defense in Depth",
            "layers": [
                {"label": "REVOKE public"},
                {"label": "SECURITY INVOKER"},
                {"label": "search_path locked"},
                {"label": "Typed functions"},
            ],
        },
    },

    # ===================================================================
    # GROUP 6: Illustrated Metaphors (5 images)
    # ===================================================================

    "thesis_02_air_traffic_control": {
        "category": DECORATIVE,
        "template": "air_traffic_tower",
        "config": {
            "title": "PostgreSQL as Air Traffic Control",
        },
    },

    "thesis_04_factory_assembly": {
        "category": DECORATIVE,
        "template": "factory_assembly",
        "config": {
            "title": "Quality Control Assembly Line",
            "stations": [
                {"label": "G1: Retrieval"},
                {"label": "G2: Citations"},
                {"label": "G3: Format"},
                {"label": "G4: Novelty"},
            ],
        },
    },

    "what_is_rag_03_student_analogy": {
        "category": DECORATIVE,
        "template": "student_analogy",
        "config": {
            "title": "RAG: The Student Analogy",
        },
    },

    "what_is_mcp_03_bouncer_metaphor": {
        "category": DECORATIVE,
        "template": "bouncer_metaphor",
        "config": {
            "title": "MCP as the Bouncer",
            "approved": ["search_chunks", "validate_slide", "commit_slide"],
            "rejected": ["DROP TABLE", "raw SQL", "DELETE *"],
        },
    },

    "what_we_built_01_meta_recursive": {
        "category": DECORATIVE,
        "template": "recursive_frames",
        "config": {
            "title": "A presentation that builds itself",
            "depth": 6,
        },
    },
}


def get_svg_image_names() -> list[str]:
    """Return all SVG image names."""
    return list(IMAGE_DEFS.keys())


def get_image_def(name: str) -> dict:
    """Get image definition by name."""
    if name not in IMAGE_DEFS:
        raise KeyError(f"Unknown image: {name}. Available: {len(IMAGE_DEFS)} images")
    return IMAGE_DEFS[name]
