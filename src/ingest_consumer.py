#!/usr/bin/env python3
"""
Kafka Consumer for Automated Content Ingestion.

Subscribes to the ``content.changes`` topic and routes each event to the
appropriate ingestion function:

* ``.md``   -> :func:`src.ingest.ingest_document`
* images    -> :func:`src.ingest_images.ingest_single_image`
* ``.json`` -> re-ingest the companion image file

Processes one event at a time. DB pool and OpenAI clients are initialised
once at startup and reused across events.

Usage:
    python -m src.ingest_consumer
"""

import asyncio
import json
import logging
import os
import signal
from pathlib import Path
from uuid import uuid4

import httpx
from aiokafka import AIOKafkaConsumer
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

from src import config
from src.db import init_pool, close_pool, get_connection
from src.ingest import ingest_document
from src.ingest_images import (
    ingest_single_image,
    load_metadata,
    SUPPORTED_EXTENSIONS as IMAGE_EXTENSIONS,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "content.changes")
KAFKA_GROUP = os.getenv("KAFKA_GROUP_ID", "ingest-consumer")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
OPENAI_USER = os.getenv("OPENAI_USER")
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() != "false"


def _build_sync_client() -> OpenAI:
    http_client = None if SSL_VERIFY else httpx.Client(verify=False)
    kwargs: dict = {"api_key": OPENAI_API_KEY}
    if OPENAI_API_BASE:
        kwargs["base_url"] = OPENAI_API_BASE
    if http_client:
        kwargs["http_client"] = http_client
    return OpenAI(**kwargs)


def _build_async_client() -> AsyncOpenAI:
    http_client = None if SSL_VERIFY else httpx.AsyncClient(verify=False)
    kwargs: dict = {"api_key": OPENAI_API_KEY}
    if OPENAI_API_BASE:
        kwargs["base_url"] = OPENAI_API_BASE
    if http_client:
        kwargs["http_client"] = http_client
    return AsyncOpenAI(**kwargs)


async def _handle_markdown(path: Path, sync_client: OpenAI) -> None:
    if not path.exists():
        logger.warning("File no longer exists, skipping: %s", path)
        return
    run_id = str(uuid4())
    async with get_connection() as conn:
        stats = await ingest_document(conn, sync_client, path, run_id=run_id)
    logger.info(
        "Markdown ingested: %s (chunks=%d, inserted=%d)",
        path.name,
        stats["chunks"],
        stats["inserted"],
    )


async def _handle_image(path: Path, async_client: AsyncOpenAI) -> None:
    if not path.exists():
        logger.warning("Image file no longer exists, skipping: %s", path)
        return
    metadata = load_metadata(path)
    if metadata is None:
        logger.warning("No valid JSON sidecar for %s, skipping", path.name)
        return
    async with get_connection() as conn:
        image_id = await ingest_single_image(conn, async_client, path, metadata)
    if image_id:
        logger.info("Image ingested: %s -> image_id=%s", path.name, image_id)
    else:
        logger.info("Image skipped (duplicate): %s", path.name)


async def _handle_json_sidecar(path: Path, async_client: AsyncOpenAI) -> None:
    """When a JSON sidecar changes, find and re-ingest the companion image."""
    stem = path.stem
    parent = path.parent
    for ext in IMAGE_EXTENSIONS:
        candidate = parent / f"{stem}{ext}"
        if candidate.exists():
            logger.info("Sidecar changed, re-ingesting companion: %s", candidate.name)
            await _handle_image(candidate, async_client)
            return
    logger.warning("No companion image found for sidecar %s", path.name)


async def consume() -> None:
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set — aborting")
        return

    await init_pool()
    await config.init_config()

    sync_client = _build_sync_client()
    async_client = _build_async_client()

    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    loop = asyncio.get_event_loop()
    shutdown = asyncio.Event()

    def _request_shutdown():
        shutdown.set()

    loop.add_signal_handler(signal.SIGINT, _request_shutdown)
    loop.add_signal_handler(signal.SIGTERM, _request_shutdown)

    await consumer.start()
    logger.info(
        "Ingest consumer started — listening on topic '%s' (group=%s)",
        KAFKA_TOPIC,
        KAFKA_GROUP,
    )

    try:
        async for msg in consumer:
            if shutdown.is_set():
                break
            try:
                payload = msg.value
                file_path = Path(payload["path"])
                event_type = payload.get("event_type", "unknown")
                logger.info("Received %s event: %s", event_type, file_path)

                ext = file_path.suffix.lower()
                if ext == ".md":
                    await _handle_markdown(file_path, sync_client)
                elif ext == ".json":
                    await _handle_json_sidecar(file_path, async_client)
                elif ext in IMAGE_EXTENSIONS:
                    await _handle_image(file_path, async_client)
                else:
                    logger.debug("Ignoring unsupported extension: %s", ext)
            except Exception:
                logger.exception("Error processing message: %s", msg.value)
    finally:
        await consumer.stop()
        await close_pool()
        logger.info("Ingest consumer stopped")


if __name__ == "__main__":
    asyncio.run(consume())
