# Model Context Protocol (MCP) Specification

**Source:** modelcontextprotocol.io
**Type:** Official Documentation
**Trust Level:** High

---

## What is MCP?

MCP (Model Context Protocol) is an open protocol that enables seamless integration between LLM applications and external data sources and tools. It provides a standardized way for applications to:
- Share contextual information with language models
- Expose tools and capabilities
- Build composable integrations and workflows

Think of it as a "USB-C port for AI applications" - a standardized interface that any tool can implement.

## Architecture

MCP uses a layered client-server architecture:

```
┌─────────────────────────────────────────────────────────┐
│                    HOST APPLICATION                      │
│              (e.g., Claude Desktop, IDE)                 │
└─────────────────────────┬───────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼                       ▼
┌─────────────────────┐   ┌─────────────────────┐
│    MCP CLIENT       │   │    MCP CLIENT       │
└──────────┬──────────┘   └──────────┬──────────┘
           │                         │
           ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐
│    MCP SERVER       │   │    MCP SERVER       │
│  (Database tools)   │   │  (File system)      │
└─────────────────────┘   └─────────────────────┘
```

### Protocol Layers
1. **Transport Layer**: JSON-RPC 2.0 messages
2. **Data Layer**: Resources, tools, prompts

## Key Components

### Resources
Servers expose resources uniquely identified by URIs that provide context to language models:
- File contents
- Database schemas
- Application-specific information
- API responses

Resources are **application-driven** - the host application determines how to incorporate context.

### Tools
Servers expose tools that language models can invoke to interact with external systems:
- Database queries
- API calls
- Computations
- File operations

Tools are **model-controlled** - the LLM discovers and invokes them automatically (with human oversight).

### Prompts
Template-based interactions that servers can expose for common operations.

## Version Negotiation

MCP uses date-based versioning (YYYY-MM-DD format):
- Current version: 2025-11-25
- Only increments on backwards-incompatible changes
- Allows incremental improvements while preserving interoperability

## Why MCP Matters

1. **Standardization**: Common interface for all AI tools
2. **Safety boundary**: Typed interfaces, not raw access
3. **Composability**: Tools can be combined and reused
4. **Observability**: Protocol-level logging and tracing

---

*Fetched: 2026-02-03*
