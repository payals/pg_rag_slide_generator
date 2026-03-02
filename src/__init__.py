"""
Postgres-First AI Slide Generator - Source Package.

Modules:
- db: Database connection pool management
- models: Pydantic schemas for MCP tools
- mcp_server: FastMCP server with 11 tools
- ingest: Content ingestion pipeline
"""

from src.db import get_connection, get_pool, close_pool, transaction, init_pool
from src.models import (
    SearchFilters,
    SlideSpec,
    ChunkResult,
    ChunkDetail,
    NoveltyResult,
    GroundingResult,
    ValidationResult,
    CitationValidationResult,
    CommitResult,
    DeckState,
    RunReport,
)

__all__ = [
    # Database
    "get_connection",
    "get_pool",
    "close_pool",
    "transaction",
    "init_pool",
    # Input Models
    "SearchFilters",
    "SlideSpec",
    # Output Models
    "ChunkResult",
    "ChunkDetail",
    "NoveltyResult",
    "GroundingResult",
    "ValidationResult",
    "CitationValidationResult",
    "CommitResult",
    "DeckState",
    "RunReport",
]
