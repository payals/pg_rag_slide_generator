#!/usr/bin/env python3
"""
Content Ingestion Pipeline for Postgres-First AI Slide Generator.

This script ingests markdown documents into the database following CHUNKING_SPEC.md:
1. Load markdown files from content directories
2. Parse metadata (title, trust level, doc type)
3. Chunk content with overlap
4. Generate embeddings via OpenAI API
5. Insert into doc/chunk tables with deduplication

Usage:
    python src/ingest.py                    # Ingest all content
    python src/ingest.py --dry-run          # Show what would be ingested
    python src/ingest.py --path content/external/rag_overview.md  # Single file
"""

import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4

import asyncpg
import httpx
import tiktoken
from dotenv import load_dotenv
from openai import OpenAI

from src.db import init_pool, close_pool, get_connection
from src import config

# Load environment (for secrets/paths only)
load_dotenv()

# Secrets/infra from env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
OPENAI_USER = os.getenv("OPENAI_USER")
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() != "false"
PERSONAL_NOTES_DIR = os.getenv("PERSONAL_NOTES_DIR", "")

# Token encoder
ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass
class DocumentMetadata:
    """Parsed metadata from document header."""
    title: str
    source: Optional[str] = None
    doc_type: str = "external"
    trust_level: str = "medium"
    tags: list = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class Chunk:
    """A text chunk with metadata."""
    content: str
    content_hash: str
    section_header: Optional[str]
    token_count: int
    overlap_tokens: int
    chunk_index: int


def count_tokens(text: str) -> int:
    """Count tokens using cl100k_base encoding."""
    return len(ENCODING.encode(text))


def compute_content_hash(content: str) -> str:
    """Normalize and hash content for deduplication."""
    normalized = ' '.join(content.split()).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def parse_metadata(content: str, file_path: Optional[Path] = None) -> DocumentMetadata:
    """Extract metadata from document header.
    
    Handles two formats:
    1. Standard markdown with # Title and **Key:** value metadata
    2. Plain text files (blogs) where first non-empty line is title
    
    Args:
        content: File content
        file_path: Optional path for inferring doc_type/trust from location
    """
    lines = content.split('\n')
    
    # Find title (first H1 or first non-empty line)
    title = "Untitled"
    for line in lines:
        if line.startswith('# '):
            title = line[2:].strip()
            break
        elif line.strip() and title == "Untitled":
            # Fall back to first non-empty line (for blog posts)
            title = line.strip()
            # Only use if it looks like a title (not too long, not metadata)
            if len(title) > 150 or '**' in title or title.startswith('-'):
                title = "Untitled"
            else:
                break
    
    # Parse metadata fields from standard format
    source = None
    doc_type = "external"
    trust_level = "medium"
    tags = []
    
    for line in lines[:20]:  # Check first 20 lines for metadata
        line_lower = line.lower()
        if line_lower.startswith('**source:**'):
            source = line.split(':', 1)[1].strip().strip('*')
        elif line_lower.startswith('**type:**'):
            type_val = line.split(':', 1)[1].strip().strip('*').lower()
            # Map to valid doc_type enum
            if 'note' in type_val:
                doc_type = 'note'
            elif 'article' in type_val:
                doc_type = 'article'
            elif 'concept' in type_val:
                doc_type = 'concept'
            elif 'blog' in type_val:
                doc_type = 'blog'
            else:
                doc_type = 'external'
        elif line_lower.startswith('**trust level:**'):
            trust_val = line.split(':', 1)[1].strip().strip('*').strip().lower()
            if trust_val in ['low', 'medium', 'high']:
                trust_level = trust_val
        elif line_lower.startswith('**tags:**'):
            tags_str = line.split(':', 1)[1].strip().strip('*')
            tags = [t.strip() for t in tags_str.split(',') if t.strip()]
    
    # Infer doc_type and trust_level from file path if not in metadata
    if file_path:
        path_str = str(file_path)
        notes_dir = PERSONAL_NOTES_DIR
        if notes_dir and notes_dir in path_str:
            if '/blogs' in path_str.lower():
                doc_type = 'blog'
            else:
                doc_type = 'note'
            trust_level = 'high'
            tags.append('tier1')
        elif 'docs/' in path_str:
            doc_type = 'article'
            trust_level = 'high'
            tags.append('tier1')
    
    return DocumentMetadata(
        title=title,
        source=source,
        doc_type=doc_type,
        trust_level=trust_level,
        tags=tags
    )


def validate_ingestion_policy(metadata: DocumentMetadata, body: str) -> tuple[bool, str, dict]:
    """
    Validate required metadata at ingestion time (G0 Ingestion Policy Gate).
    
    Rules:
    - FAIL: title is "Untitled"
    - FAIL: trust_level not in ['low', 'medium', 'high']
    - FAIL: content body has < 50 tokens (too short to chunk meaningfully)
    - WARN (pass with note): missing tags (empty list)
    
    Args:
        metadata: Parsed document metadata
        body: Extracted document body text
        
    Returns:
        Tuple of (is_valid, reason, details_dict)
    """
    errors = []
    warnings = []
    
    if metadata.title == "Untitled":
        errors.append("Title is 'Untitled'")
    
    if metadata.trust_level not in ("low", "medium", "high"):
        errors.append(f"Invalid trust_level: '{metadata.trust_level}'")
    
    body_tokens = count_tokens(body) if body else 0
    if body_tokens < 50:
        errors.append(f"Body too short: {body_tokens} tokens (min 50)")
    
    if not metadata.tags:
        warnings.append("Missing tags (empty list)")
    
    if errors:
        reason = "; ".join(errors)
        return False, reason, {"errors": errors, "warnings": warnings}
    
    reason = "All checks passed"
    if warnings:
        reason += f" (warnings: {'; '.join(warnings)})"
    return True, reason, {"errors": [], "warnings": warnings}


async def log_g0_gate(
    conn: asyncpg.Connection,
    run_id: str,
    valid: bool,
    reason: str,
    details: dict,
) -> None:
    """Log G0 ingestion policy gate result to gate_log table.
    
    Uses deck_id=NULL since there's no deck during ingestion.
    """
    try:
        await conn.execute("""
            INSERT INTO gate_log (run_id, deck_id, slide_no, gate_name, decision, reason, payload)
            VALUES ($1, NULL, NULL, 'g0_ingestion', $2, $3, $4)
        """, run_id, 'pass' if valid else 'fail', reason, json.dumps(details))
    except Exception as e:
        # Don't crash ingestion if gate_log table doesn't exist
        print(f"  Warning: Could not log G0 gate: {e}")


def extract_body(content: str) -> str:
    """Remove metadata header from content, keeping the body."""
    lines = content.split('\n')
    body_start = 0
    
    # Skip past metadata section (ends at first ---)
    # Structure: # Title, metadata lines, ---, body content
    for i, line in enumerate(lines):
        if line.strip() == '---':
            body_start = i + 1
            break
    
    # Also remove trailing --- and footer
    body_lines = lines[body_start:]
    body_end = len(body_lines)
    for i in range(len(body_lines) - 1, -1, -1):
        if body_lines[i].strip() == '---':
            body_end = i
            break
    
    return '\n'.join(body_lines[:body_end]).strip()


def split_into_sections(content: str) -> list[tuple[Optional[str], str]]:
    """Split content by H2 headers, returning (header, body) pairs."""
    sections = []
    current_header = None
    current_body = []
    
    for line in content.split('\n'):
        if line.startswith('## '):
            # Save previous section
            if current_body:
                sections.append((current_header, '\n'.join(current_body).strip()))
            current_header = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)
    
    # Don't forget last section
    if current_body:
        sections.append((current_header, '\n'.join(current_body).strip()))
    
    return sections


def chunk_text(text: str, section_header: Optional[str], start_index: int) -> list[Chunk]:
    """Chunk text with overlap, respecting paragraph boundaries."""
    chunks = []
    paragraphs = re.split(r'\n\n+', text)
    
    current_content = ""
    current_tokens = 0
    overlap_text = ""
    overlap_tokens = 0
    chunk_index = start_index
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        para_tokens = count_tokens(para)
        
        # If adding this paragraph exceeds limit, finalize current chunk
        if current_tokens + para_tokens > config.get("chunk_size_tokens", 700) and current_content:
            # Only save if above minimum size
            if current_tokens >= config.get("min_chunk_size_tokens", 50):
                chunks.append(Chunk(
                    content=current_content.strip(),
                    content_hash=compute_content_hash(current_content),
                    section_header=section_header,
                    token_count=current_tokens,
                    overlap_tokens=overlap_tokens,
                    chunk_index=chunk_index
                ))
                chunk_index += 1
            
            # Compute overlap from end of current chunk
            overlap_text = get_overlap_text(current_content, config.get("chunk_overlap_tokens", 100))
            overlap_tokens = count_tokens(overlap_text) if overlap_text else 0
            
            # Start new chunk with overlap
            current_content = overlap_text + "\n\n" + para if overlap_text else para
            current_tokens = overlap_tokens + para_tokens
        else:
            # Add paragraph to current chunk
            if current_content:
                current_content += "\n\n" + para
            else:
                current_content = para
            current_tokens += para_tokens
    
    # Don't forget last chunk
    if current_content and current_tokens >= config.get("min_chunk_size_tokens", 50):
        chunks.append(Chunk(
            content=current_content.strip(),
            content_hash=compute_content_hash(current_content),
            section_header=section_header,
            token_count=current_tokens,
            overlap_tokens=overlap_tokens,
            chunk_index=chunk_index
        ))
    
    return chunks


def get_overlap_text(text: str, target_tokens: int) -> str:
    """Get approximately target_tokens from the end of text."""
    words = text.split()
    overlap_words = []
    tokens = 0
    
    for word in reversed(words):
        word_tokens = count_tokens(word)
        if tokens + word_tokens > target_tokens:
            break
        overlap_words.insert(0, word)
        tokens += word_tokens
    
    return ' '.join(overlap_words)


def chunk_document(content: str) -> list[Chunk]:
    """Chunk entire document following CHUNKING_SPEC.md."""
    body = extract_body(content)
    sections = split_into_sections(body)
    
    all_chunks = []
    chunk_index = 0
    
    for section_header, section_body in sections:
        if not section_body.strip():
            continue
        section_chunks = chunk_text(section_body, section_header, chunk_index)
        all_chunks.extend(section_chunks)
        if section_chunks:
            chunk_index = section_chunks[-1].chunk_index + 1
    
    return all_chunks


async def get_embedding(client: OpenAI, text: str) -> list[float]:
    """Get embedding for text using OpenAI API."""
    kwargs = {
        "model": config.get("openai_embedding_model", "text-embedding-3-small"),
        "input": text
    }
    if OPENAI_USER:
        kwargs["user"] = OPENAI_USER
    
    response = client.embeddings.create(**kwargs)
    return response.data[0].embedding


async def ingest_document(
    conn: asyncpg.Connection,
    client: OpenAI,
    file_path: Path,
    dry_run: bool = False,
    run_id: Optional[str] = None,
) -> dict:
    """Ingest a single document into the database."""
    content = file_path.read_text(encoding='utf-8')
    metadata = parse_metadata(content, file_path)
    
    # G0 Ingestion Policy Gate
    body = extract_body(content)
    g0_valid, g0_reason, g0_details = validate_ingestion_policy(metadata, body)
    g0_details["file"] = str(file_path)
    g0_details["title"] = metadata.title
    
    if run_id and not dry_run:
        await log_g0_gate(conn, run_id, g0_valid, g0_reason, g0_details)
    
    if not g0_valid:
        print(f"  [G0 FAIL] Skipping {file_path.name}: {g0_reason}")
        return {
            "file": str(file_path),
            "title": metadata.title,
            "chunks": 0,
            "tokens": 0,
            "skipped": 0,
            "inserted": 0,
            "g0_result": "fail",
            "g0_reason": g0_reason,
        }
    
    chunks = chunk_document(content)
    
    stats = {
        "file": str(file_path),
        "title": metadata.title,
        "chunks": len(chunks),
        "tokens": sum(c.token_count for c in chunks),
        "skipped": 0,
        "inserted": 0
    }
    
    if dry_run:
        print(f"  [DRY RUN] Would ingest: {metadata.title}")
        print(f"            Chunks: {len(chunks)}, Tokens: {stats['tokens']}")
        return stats
    
    # Check if document already exists by source_path
    existing = await conn.fetchval(
        "SELECT doc_id FROM doc WHERE source_path = $1",
        str(file_path)
    )
    
    if existing:
        print(f"  Updating existing document: {metadata.title}")
        doc_id = existing
        # Delete existing chunks to re-ingest
        await conn.execute("DELETE FROM chunk WHERE doc_id = $1", doc_id)
        # Update doc metadata
        await conn.execute("""
            UPDATE doc SET 
                title = $2, doc_type = $3, trust_level = $4, 
                tags = $5, updated_at = now()
            WHERE doc_id = $1
        """, doc_id, metadata.title, metadata.doc_type, 
            metadata.trust_level, metadata.tags)
    else:
        # Insert new document
        doc_id = await conn.fetchval("""
            INSERT INTO doc (doc_type, title, source_path, trust_level, tags)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING doc_id
        """, metadata.doc_type, metadata.title, str(file_path),
            metadata.trust_level, metadata.tags)
        print(f"  Created document: {metadata.title}")
    
    # Insert chunks
    for chunk in chunks:
        # Check for duplicate content
        existing_chunk = await conn.fetchval(
            "SELECT chunk_id FROM chunk WHERE content_hash = $1",
            chunk.content_hash
        )
        
        if existing_chunk:
            stats["skipped"] += 1
            continue
        
        # Get embedding
        embedding = await get_embedding(client, chunk.content)
        
        # Insert chunk
        await conn.execute("""
            INSERT INTO chunk (
                doc_id, chunk_index, content, content_hash,
                embedding, token_count, overlap_tokens, section_header
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, doc_id, chunk.chunk_index, chunk.content, chunk.content_hash,
            str(embedding), chunk.token_count, chunk.overlap_tokens,
            chunk.section_header)
        
        stats["inserted"] += 1
    
    print(f"    Inserted: {stats['inserted']}, Skipped (dupe): {stats['skipped']}")
    return stats


async def main(dry_run: bool = False, single_path: Optional[str] = None):
    """Main ingestion entry point."""
    run_id = str(uuid4())
    
    print("=" * 60)
    print("Content Ingestion Pipeline")
    print(f"Run ID: {run_id}")
    print("=" * 60)
    
    # Validate environment
    if not OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)
    
    # Initialize DB pool and config from Postgres
    await init_pool()
    await config.init_config()
    
    print(f"Embedding model: {config.get('openai_embedding_model')}")
    print(f"Chunk size: {config.get('chunk_size_tokens')} tokens, Overlap: {config.get('chunk_overlap_tokens')}")
    print(f"SSL Verify: {SSL_VERIFY}")
    print()
    
    # Initialize OpenAI client
    http_client = None if SSL_VERIFY else httpx.Client(verify=False)
    client_kwargs = {"api_key": OPENAI_API_KEY}
    if OPENAI_API_BASE:
        client_kwargs["base_url"] = OPENAI_API_BASE
    if http_client:
        client_kwargs["http_client"] = http_client
    
    openai_client = OpenAI(**client_kwargs)
    
    try:
        async with get_connection() as conn:
            # Collect files to ingest
            if single_path:
                files = [Path(single_path)]
            else:
                files = []
                
                external_dir = Path("content/external")
                if external_dir.exists():
                    files.extend(external_dir.glob("*.md"))
                
                if PERSONAL_NOTES_DIR:
                    notes_root = Path(PERSONAL_NOTES_DIR)
                    if notes_root.exists():
                        for md in notes_root.rglob("*.md"):
                            files.append(md)
                
                project_overview = Path("docs/PROJECT_OVERVIEW.md")
                if project_overview.exists():
                    files.append(project_overview)
            
            print(f"Found {len(files)} files to ingest")
            print("-" * 60)
            
            total_stats = {
                "files": 0, "chunks": 0, "tokens": 0,
                "inserted": 0, "skipped": 0
            }
            
            for file_path in sorted(files):
                print(f"\nProcessing: {file_path.name}")
                stats = await ingest_document(conn, openai_client, file_path, dry_run, run_id=run_id)
                total_stats["files"] += 1
                total_stats["chunks"] += stats["chunks"]
                total_stats["tokens"] += stats["tokens"]
                total_stats["inserted"] += stats["inserted"]
                total_stats["skipped"] += stats["skipped"]
            
            print()
            print("=" * 60)
            print("SUMMARY")
            print("=" * 60)
            print(f"Files processed: {total_stats['files']}")
            print(f"Total chunks: {total_stats['chunks']}")
            print(f"Total tokens: {total_stats['tokens']}")
            print(f"Chunks inserted: {total_stats['inserted']}")
            print(f"Chunks skipped (duplicates): {total_stats['skipped']}")
            
            if not dry_run:
                print()
                print("-" * 60)
                print("Quality Checks")
                print("-" * 60)
                
                result = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total,
                        AVG(token_count)::int as avg_tokens,
                        MIN(token_count) as min_tokens,
                        MAX(token_count) as max_tokens
                    FROM chunk
                """)
                print(f"Chunk stats: {result['total']} chunks, "
                      f"avg={result['avg_tokens']}, min={result['min_tokens']}, max={result['max_tokens']}")
                
                missing = await conn.fetchval(
                    "SELECT COUNT(*) FROM chunk WHERE embedding IS NULL"
                )
                print(f"Missing embeddings: {missing}")
                
                missing_headers = await conn.fetchval(
                    "SELECT COUNT(*) FROM chunk WHERE section_header IS NULL"
                )
                print(f"Missing section headers: {missing_headers}")
    finally:
        if http_client:
            http_client.close()
        await close_pool()
    
    print()
    print("✅ Ingestion complete!")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Ingest content into slide generator database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be ingested without inserting")
    parser.add_argument("--path", type=str, help="Ingest a single file")
    args = parser.parse_args()
    
    asyncio.run(main(dry_run=args.dry_run, single_path=args.path))
