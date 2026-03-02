#!/usr/bin/env python3
"""
Image Ingestion Pipeline for Postgres-First AI Slide Generator.

This script ingests image assets into the database for RAG-based image selection:
1. Scan content/images/ for image files (.png, .jpg, .jpeg, .svg, .webp)
2. For each image, look for companion .json sidecar file
3. Validate JSON against ImageMetadata Pydantic model
4. Generate embedding from caption + alt_text
5. Insert into doc + image_asset tables

Usage:
    python src/ingest_images.py                     # Ingest all images
    python src/ingest_images.py --dry-run           # Preview without inserting
    python src/ingest_images.py --path content/images/rag_flow.png  # Single image
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import asyncpg
import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import ValidationError

from src.models import ImageMetadata
from src.db import init_pool, close_pool, get_connection
from src import config

# Load environment (for secrets/paths only)
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Secrets/infra from env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
OPENAI_USER = os.getenv("OPENAI_USER")
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() != "false"
IMAGE_CONTENT_DIR = Path(os.getenv("IMAGE_CONTENT_DIR", "content/images"))

# Supported image extensions
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}


async def get_openai_client() -> AsyncOpenAI:
    """Get async OpenAI client."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    http_client = None if SSL_VERIFY else httpx.AsyncClient(verify=False)
    client_kwargs = {"api_key": OPENAI_API_KEY}
    if OPENAI_API_BASE:
        client_kwargs["base_url"] = OPENAI_API_BASE
    if http_client:
        client_kwargs["http_client"] = http_client

    return AsyncOpenAI(**client_kwargs)


async def get_embedding(client: AsyncOpenAI, text: str) -> list[float]:
    """Get embedding for text using OpenAI API."""
    kwargs = {
        "model": config.get("openai_embedding_model", "text-embedding-3-small"),
        "input": text,
    }
    if OPENAI_USER:
        kwargs["user"] = OPENAI_USER

    response = await client.embeddings.create(**kwargs)
    return response.data[0].embedding


def compute_image_hash(image_path: Path) -> str:
    """Compute SHA-256 hash of image file for deduplication."""
    sha256 = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_image_dimensions(image_path: Path) -> tuple[Optional[int], Optional[int]]:
    """
    Get image dimensions if possible.
    
    Returns (width, height) tuple, or (None, None) if unable to determine.
    """
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return img.size
    except ImportError:
        logger.debug("Pillow not installed, skipping dimension detection")
        return None, None
    except Exception as e:
        logger.debug(f"Could not read image dimensions for {image_path}: {e}")
        return None, None


def find_images(base_dir: Path, single_path: Optional[Path] = None) -> list[Path]:
    """
    Find all image files in the given directory.
    
    Args:
        base_dir: Base directory to scan
        single_path: If provided, only process this single image
        
    Returns:
        List of image file paths
    """
    if single_path:
        if single_path.exists() and single_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [single_path]
        else:
            logger.warning(f"File not found or unsupported format: {single_path}")
            return []

    if not base_dir.exists():
        logger.warning(f"Image directory does not exist: {base_dir}")
        return []

    images = []
    for ext in SUPPORTED_EXTENSIONS:
        images.extend(base_dir.glob(f"*{ext}"))
        images.extend(base_dir.glob(f"*{ext.upper()}"))
    
    # Deduplicate (case-insensitive glob may return dupes)
    seen = set()
    unique = []
    for img in sorted(images):
        if img not in seen:
            seen.add(img)
            unique.append(img)

    # When both a raster (PNG/JPG) and SVG exist for the same stem,
    # prefer the raster — the SVG may be a Mermaid placeholder showing
    # raw code text instead of a rendered diagram.
    RASTER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    stems_with_raster = {
        img.stem for img in unique if img.suffix.lower() in RASTER_EXTS
    }
    filtered = [
        img for img in unique
        if not (img.suffix.lower() == ".svg" and img.stem in stems_with_raster)
    ]
    skipped = len(unique) - len(filtered)
    if skipped:
        logger.info(f"Skipped {skipped} SVG(s) that have raster equivalents")

    return filtered


def load_metadata(image_path: Path) -> Optional[ImageMetadata]:
    """
    Load and validate the JSON sidecar file for an image.
    
    Looks for a .json file with the same stem as the image.
    e.g., rag_flow.png -> rag_flow.json
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Validated ImageMetadata or None if invalid/missing
    """
    json_path = image_path.with_suffix(".json")
    
    if not json_path.exists():
        logger.warning(f"SKIP: No JSON metadata for {image_path.name} (expected {json_path.name})")
        return None

    try:
        with open(json_path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"SKIP: Invalid JSON in {json_path.name}: {e}")
        return None

    try:
        metadata = ImageMetadata(**data)
        return metadata
    except ValidationError as e:
        logger.error(f"SKIP: Validation failed for {json_path.name}:")
        for error in e.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            logger.error(f"  - {field}: {error['msg']}")
        return None


async def ingest_single_image(
    conn: asyncpg.Connection,
    client: AsyncOpenAI,
    image_path: Path,
    metadata: ImageMetadata,
    dry_run: bool = False,
) -> Optional[str]:
    """
    Ingest a single image into the database.
    
    Args:
        conn: Database connection
        client: OpenAI client for embeddings
        image_path: Path to the image file
        metadata: Validated image metadata
        dry_run: If True, don't actually insert
        
    Returns:
        image_id if inserted, None if skipped
    """
    # Compute hash for deduplication
    content_hash = compute_image_hash(image_path)
    
    # Check for duplicate
    existing = await conn.fetchval(
        "SELECT doc_id FROM doc WHERE content_hash = $1", content_hash
    )
    if existing:
        logger.info(f"SKIP: {image_path.name} already ingested (hash match)")
        return None

    # Get storage path relative to content/images/
    try:
        storage_path = str(image_path.relative_to(IMAGE_CONTENT_DIR))
    except ValueError:
        storage_path = image_path.name

    if dry_run:
        logger.info(f"DRY RUN: Would ingest {image_path.name}")
        logger.info(f"  Caption: {metadata.caption}")
        logger.info(f"  Alt text: {metadata.alt_text}")
        logger.info(f"  License: {metadata.license}")
        logger.info(f"  Attribution: {metadata.attribution}")
        logger.info(f"  Style: {metadata.style}")
        logger.info(f"  Use cases: {metadata.use_cases}")
        return None

    # Generate embedding from caption + alt_text
    embed_text = f"{metadata.caption} {metadata.alt_text}"
    embedding = await get_embedding(client, embed_text)

    # Get image dimensions
    width, height = get_image_dimensions(image_path)

    # Insert doc record
    doc_id = await conn.fetchval("""
        INSERT INTO doc (doc_type, title, source_path, trust_level, tags, content_hash)
        VALUES ('image', $1, $2, 'high', $3, $4)
        RETURNING doc_id
    """,
        metadata.caption[:100],  # title = truncated caption
        str(image_path),
        metadata.use_cases if metadata.use_cases else [],
        content_hash,
    )

    # Insert image_asset record
    style_value = metadata.style if metadata.style else None
    image_id = await conn.fetchval("""
        INSERT INTO image_asset (
            doc_id, storage_path, caption, alt_text, caption_embedding,
            use_cases, license, attribution, style, width, height
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::image_style, $10, $11)
        RETURNING image_id
    """,
        doc_id,
        storage_path,
        metadata.caption,
        metadata.alt_text,
        str(embedding),
        metadata.use_cases if metadata.use_cases else [],
        metadata.license,
        metadata.attribution,
        style_value,
        width,
        height,
    )

    logger.info(f"INGESTED: {image_path.name} -> image_id={image_id}")
    return str(image_id)


async def purge_image_data(conn: asyncpg.Connection) -> int:
    """
    Delete all image-related data from the database.

    FK-safe order:
    1. NULL out slide.image_id (FK to image_asset without CASCADE)
    2. DELETE FROM doc WHERE doc_type = 'image' (cascades to image_asset via doc_id FK)

    Returns:
        Number of doc rows deleted
    """
    # Step 1: NULL out slide.image_id to avoid FK violations
    result = await conn.execute(
        "UPDATE slide SET image_id = NULL WHERE image_id IS NOT NULL"
    )
    nulled = int(result.split()[-1]) if result else 0
    logger.info(f"PURGE: Cleared image_id on {nulled} slide(s)")

    # Step 2: Delete doc rows of type 'image' (cascades to image_asset)
    result = await conn.execute(
        "DELETE FROM doc WHERE doc_type = 'image'"
    )
    deleted = int(result.split()[-1]) if result else 0
    logger.info(f"PURGE: Deleted {deleted} image doc(s) (cascaded to image_asset)")

    return deleted


async def ingest_images(
    image_dir: Optional[Path] = None,
    single_path: Optional[Path] = None,
    dry_run: bool = False,
    purge: bool = False,
) -> dict:
    """
    Main ingestion function.
    
    Args:
        image_dir: Directory containing images (default: content/images/)
        single_path: If provided, only process this single image
        dry_run: If True, preview without inserting
        purge: If True, delete all existing image data before ingestion
        
    Returns:
        Report dict with counts
    """
    image_dir = image_dir or IMAGE_CONTENT_DIR
    
    # Find images
    images = find_images(image_dir, single_path)
    logger.info(f"Found {len(images)} image(s) in {image_dir}")
    
    if not images and not purge:
        return {"found": 0, "ingested": 0, "skipped": 0, "errors": 0, "purged": 0}

    report = {"found": len(images), "ingested": 0, "skipped": 0, "errors": 0, "purged": 0, "details": []}

    # Initialize DB pool and config from Postgres
    await init_pool()
    await config.init_config()

    client = await get_openai_client() if not dry_run else None

    try:
        async with get_connection() as conn:
            if purge and not dry_run:
                report["purged"] = await purge_image_data(conn)
            elif purge and dry_run:
                logger.info("PURGE: Dry run — would delete all image docs and clear slide.image_id")

            for image_path in images:
                metadata = load_metadata(image_path)
                if metadata is None:
                    report["skipped"] += 1
                    report["details"].append({"file": image_path.name, "status": "skipped", "reason": "missing or invalid metadata"})
                    continue

                try:
                    result = await ingest_single_image(
                        conn, client, image_path, metadata, dry_run
                    )
                    if result:
                        report["ingested"] += 1
                        report["details"].append({"file": image_path.name, "status": "ingested", "image_id": result})
                    else:
                        if not dry_run:
                            report["skipped"] += 1
                            report["details"].append({"file": image_path.name, "status": "skipped", "reason": "duplicate"})
                        else:
                            report["details"].append({"file": image_path.name, "status": "dry_run"})
                except Exception as e:
                    logger.error(f"ERROR: Failed to ingest {image_path.name}: {e}")
                    report["errors"] += 1
                    report["details"].append({"file": image_path.name, "status": "error", "reason": str(e)})
    finally:
        await close_pool()

    return report


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Ingest image assets into the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python src/ingest_images.py                     # Ingest all images
    python src/ingest_images.py --dry-run           # Preview without inserting
    python src/ingest_images.py --path content/images/rag_flow.png  # Single image
    python src/ingest_images.py --purge             # Delete existing images, then re-ingest
        """
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview images to ingest without inserting"
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete all existing image data before re-ingestion"
    )
    parser.add_argument(
        "--path",
        type=str,
        help="Path to a single image file to ingest"
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Directory containing images (default: content/images/)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    single_path = Path(args.path) if args.path else None
    image_dir = Path(args.dir) if args.dir else None

    report = asyncio.run(ingest_images(
        image_dir=image_dir,
        single_path=single_path,
        dry_run=args.dry_run,
        purge=args.purge,
    ))

    # Print summary
    print("\n" + "=" * 50)
    print("IMAGE INGESTION REPORT")
    print("=" * 50)
    if report.get("purged"):
        print(f"  Purged:   {report['purged']}")
    print(f"  Found:    {report['found']}")
    print(f"  Ingested: {report['ingested']}")
    print(f"  Skipped:  {report['skipped']}")
    print(f"  Errors:   {report['errors']}")
    
    if report.get("details"):
        print("\nDetails:")
        for detail in report["details"]:
            status = detail["status"].upper()
            name = detail["file"]
            reason = detail.get("reason", detail.get("image_id", ""))
            print(f"  [{status}] {name}: {reason}")
    
    print("=" * 50)


if __name__ == "__main__":
    main()
