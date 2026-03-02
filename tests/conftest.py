"""
Shared pytest fixtures for the Postgres-First AI Slide Generator tests.

Provides:
- Database connections with automatic rollback
- Test data factories
- Mock clients for OpenAI
- Common test utilities
"""

import json
import os
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from dotenv import load_dotenv

# Load test environment
load_dotenv()

# Test database URL (separate from production!)
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", os.getenv("DATABASE_URL"))

# -----------------------------------------------------------------------------
# Database Fixtures
# -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_db():
    """
    Fresh database connection with transaction rollback.
    
    Each test runs in a transaction that is rolled back after the test,
    ensuring test isolation and no data pollution.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not configured")
    
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    tr = conn.transaction()
    await tr.start()
    
    try:
        yield conn
    finally:
        await tr.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def seeded_db(test_db):
    """
    Database with minimal test data for retrieval tests.
    
    Creates:
    - 3 test documents
    - 6 test chunks with embeddings
    """
    # Insert test documents
    doc_ids = []
    for i, (title, doc_type, trust) in enumerate([
        ("RAG Overview", "external", "high"),
        ("Postgres AI Guide", "article", "medium"),
        ("MCP Specification", "external", "high"),
    ]):
        doc_id = await test_db.fetchval("""
            INSERT INTO doc (doc_type, title, trust_level, tags)
            VALUES ($1, $2, $3, $4)
            RETURNING doc_id
        """, doc_type, title, trust, ["test", f"doc{i}"])
        doc_ids.append(doc_id)
    
    # Insert test chunks with fake embeddings
    # Using simple embeddings that create predictable similarity patterns
    test_chunks = [
        (doc_ids[0], 0, "RAG combines retrieval with generation for accurate AI responses.", get_test_embedding("rag retrieval generation")),
        (doc_ids[0], 1, "Semantic search uses vector embeddings to find similar content.", get_test_embedding("semantic search vectors")),
        (doc_ids[1], 0, "Postgres with pgvector enables native vector similarity search.", get_test_embedding("postgres pgvector native")),
        (doc_ids[1], 1, "The database can serve as the control plane for AI applications.", get_test_embedding("database control plane ai")),
        (doc_ids[2], 0, "MCP provides typed tool interfaces for LLM interactions.", get_test_embedding("mcp tools llm interface")),
        (doc_ids[2], 1, "Tools expose safe, validated operations without raw database access.", get_test_embedding("tools validation safe database")),
    ]
    
    for doc_id, idx, content, embedding in test_chunks:
        content_hash = f"test_hash_{doc_id}_{idx}"
        await test_db.execute("""
            INSERT INTO chunk (doc_id, chunk_index, content, content_hash, embedding, token_count)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, doc_id, idx, content, content_hash, str(embedding), len(content.split()) * 2)
    
    yield test_db


@pytest_asyncio.fixture
async def test_deck(test_db):
    """
    Create a test deck for slide operations.
    
    Returns the deck_id for use in tests.
    """
    deck_id = await test_db.fetchval("""
        SELECT fn_create_deck('Test Presentation Topic', 14, '{}'::jsonb, 'Test description')
    """)
    yield deck_id


@pytest_asyncio.fixture
async def seeded_db_with_images(seeded_db):
    """
    Database with test documents AND images.
    
    Extends seeded_db with an image doc and image_asset record.
    """
    # Insert image doc
    doc_id = await seeded_db.fetchval("""
        INSERT INTO doc (doc_type, title, trust_level, tags, content_hash)
        VALUES ('image', 'RAG Architecture Diagram', 'high', ARRAY['diagram'], 'img_hash_001')
        RETURNING doc_id
    """)
    
    # Insert image asset with embedding
    embedding = get_test_embedding("RAG architecture diagram flow")
    await seeded_db.execute("""
        INSERT INTO image_asset (doc_id, storage_path, caption, alt_text,
                                 caption_embedding, use_cases, license, attribution, style,
                                 width, height)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::image_style, $10, $11)
    """, doc_id, "rag_architecture.png", "RAG architecture diagram showing retrieval flow",
         "Diagram showing retrieval, augmentation, generation pipeline",
         str(embedding), ["architecture", "diagram"], "CC-BY-4.0", "Test Author", "diagram",
         800, 600)
    
    # Insert a second image for search diversity
    doc_id2 = await seeded_db.fetchval("""
        INSERT INTO doc (doc_type, title, trust_level, tags, content_hash)
        VALUES ('image', 'MCP Tools Screenshot', 'high', ARRAY['screenshot'], 'img_hash_002')
        RETURNING doc_id
    """)
    
    embedding2 = get_test_embedding("MCP server tools interface screenshot")
    await seeded_db.execute("""
        INSERT INTO image_asset (doc_id, storage_path, caption, alt_text,
                                 caption_embedding, use_cases, license, attribution, style,
                                 width, height)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::image_style, $10, $11)
    """, doc_id2, "mcp_tools.png", "MCP server tools showing typed interfaces",
         "Screenshot of MCP tool listing with function signatures",
         str(embedding2), ["tools", "interface"], "CC-BY-4.0", "Test Author", "screenshot",
         1024, 768)
    
    yield seeded_db


# -----------------------------------------------------------------------------
# Test Data Factories
# -----------------------------------------------------------------------------


def get_test_embedding(text: str, dim: int = 1536) -> list[float]:
    """
    Generate a deterministic pseudo-embedding for testing.
    
    Creates embeddings that have predictable similarity relationships:
    - Same text = identical embedding
    - Similar text = similar embeddings (roughly)
    
    NOT for production - only for testing similarity behaviors.
    """
    import hashlib
    
    # Hash the text to get consistent values
    text_hash = hashlib.md5(text.encode()).hexdigest()
    
    # Convert hash to float values
    embedding = []
    for i in range(dim):
        # Use hash characters and position to generate values
        char_idx = i % len(text_hash)
        val = (int(text_hash[char_idx], 16) + i) / (16 + dim)
        # Add variation based on text length
        val += len(text) / 1000
        embedding.append(val)
    
    # Normalize to unit length (important for cosine similarity)
    magnitude = sum(v ** 2 for v in embedding) ** 0.5
    return [v / magnitude for v in embedding]


def get_test_document(overrides: Optional[dict] = None) -> str:
    """
    Generate a test markdown document.
    
    Args:
        overrides: Dict to override default values
    
    Returns:
        Markdown string formatted like content files
    """
    defaults = {
        "title": "Test Document",
        "source": "https://example.com/test",
        "type": "external",
        "trust_level": "medium",
        "tags": "test, example",
        "body": """## Introduction

This is a test document for the ingestion pipeline.

## Main Content

Here is the main content with multiple paragraphs.

This paragraph discusses RAG and retrieval augmented generation.

## Conclusion

Final thoughts on the test document."""
    }
    d = {**defaults, **(overrides or {})}
    
    return f"""# {d['title']}

**Source:** {d['source']}
**Type:** {d['type']}
**Trust Level:** {d['trust_level']}
**Tags:** {d['tags']}

---

{d['body']}

---
"""


def get_test_slide_spec(overrides: Optional[dict] = None) -> dict:
    """
    Generate a valid slide specification.
    
    Args:
        overrides: Dict to override default values
    
    Returns:
        Slide spec dict matching expected schema
    """
    defaults = {
        "intent": "problem",
        "title": "The Problem with External Vector Databases",
        "bullets": [
            "Data duplication across systems increases complexity",
            "Network latency for every similarity search",
            "Additional infrastructure to manage and scale",
        ],
        "speaker_notes": "This slide covers the key challenges organizations face when using external vector databases. The main pain points are operational complexity and latency.",
        "citations": []
    }
    return {**defaults, **(overrides or {})}


def get_test_image_asset(overrides: Optional[dict] = None) -> dict:
    """
    Generate test image asset data.
    
    Args:
        overrides: Dict to override default values
        
    Returns:
        Image asset data dict
    """
    defaults = {
        "storage_path": "test_diagram.png",
        "caption": "Test diagram showing RAG architecture flow",
        "alt_text": "Diagram with boxes and arrows",
        "use_cases": ["diagram", "architecture"],
        "license": "CC-BY-4.0",
        "attribution": "Test Author",
        "style": "diagram",
        "width": 800,
        "height": 600,
    }
    return {**defaults, **(overrides or {})}


def get_test_image_metadata(overrides: Optional[dict] = None) -> dict:
    """
    Generate test image JSON metadata (matching ImageMetadata schema).
    
    Args:
        overrides: Dict to override default values
        
    Returns:
        Image metadata dict
    """
    defaults = {
        "caption": "Test diagram showing RAG architecture",
        "alt_text": "Diagram with three connected boxes",
        "use_cases": ["architecture", "diagram"],
        "license": "CC-BY-4.0",
        "attribution": "Test Author",
        "style": "diagram",
    }
    return {**defaults, **(overrides or {})}


def get_test_chunk(overrides: Optional[dict] = None) -> dict:
    """
    Generate test chunk data.
    
    Args:
        overrides: Dict to override default values
    
    Returns:
        Chunk data dict
    """
    defaults = {
        "content": "Test chunk content about RAG and Postgres integration.",
        "section_header": "Introduction",
        "token_count": 150,
        "overlap_tokens": 0,
    }
    return {**defaults, **(overrides or {})}


# -----------------------------------------------------------------------------
# Mock Clients
# -----------------------------------------------------------------------------


@dataclass
class MockEmbeddingResponse:
    """Mock response from OpenAI embeddings API."""
    embedding: list[float]
    
    class Data:
        def __init__(self, embedding):
            self.embedding = embedding
    
    def __init__(self, embedding):
        self.data = [self.Data(embedding)]


@dataclass  
class MockChatMessage:
    """Mock chat completion message."""
    content: str
    role: str = "assistant"


@dataclass
class MockChatChoice:
    """Mock chat completion choice."""
    message: MockChatMessage
    finish_reason: str = "stop"


@dataclass
class MockChatResponse:
    """Mock response from OpenAI chat completions API."""
    content: str
    
    def __init__(self, content):
        self.choices = [MockChatChoice(MockChatMessage(content))]


class MockOpenAIClient:
    """
    Mock OpenAI client for testing without API calls.
    
    Tracks call count and returns configurable responses.
    """
    
    def __init__(self, embedding_responses=None, chat_responses=None):
        self.embedding_responses = embedding_responses or []
        self.chat_responses = chat_responses or []
        self.embedding_call_count = 0
        self.chat_call_count = 0
    
    @property
    def embeddings(self):
        return self
    
    @property
    def chat(self):
        return self
    
    @property
    def completions(self):
        return self
    
    def create(self, **kwargs):
        """Handle both embeddings.create and chat.completions.create."""
        if "input" in kwargs:
            # Embeddings call
            self.embedding_call_count += 1
            if self.embedding_responses:
                return self.embedding_responses.pop(0)
            # Return deterministic embedding based on input
            text = kwargs["input"] if isinstance(kwargs["input"], str) else kwargs["input"][0]
            return MockEmbeddingResponse(get_test_embedding(text))
        else:
            # Chat call
            self.chat_call_count += 1
            if self.chat_responses:
                return self.chat_responses.pop(0)
            return MockChatResponse('{"title": "Test", "bullets": ["One", "Two", "Three"]}')


@pytest.fixture
def mock_openai():
    """Provide a mock OpenAI client."""
    return MockOpenAIClient()


# -----------------------------------------------------------------------------
# Test Utilities
# -----------------------------------------------------------------------------


def assert_valid_uuid(value: str):
    """Assert that a string is a valid UUID."""
    from uuid import UUID
    try:
        UUID(str(value))
    except (ValueError, AttributeError):
        pytest.fail(f"Invalid UUID: {value}")


def assert_json_structure(data: dict, required_keys: list[str]):
    """Assert that a dict contains all required keys."""
    missing = [k for k in required_keys if k not in data]
    if missing:
        pytest.fail(f"Missing required keys: {missing}")


# -----------------------------------------------------------------------------
# Pytest Configuration
# -----------------------------------------------------------------------------


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "e2e: marks tests as end-to-end tests")
