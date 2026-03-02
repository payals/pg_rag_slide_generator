#!/usr/bin/env python3
"""
File Watcher for Automated Content Ingestion.

Monitors content/external/*.md and content/images/* for create/modify events,
then publishes change notifications to Kafka topic ``content.changes``.
Deletions are intentionally ignored.

Usage:
    python -m src.file_watcher
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from kafka import KafkaProducer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
from watchdog.observers import Observer

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "content.changes")

WATCH_DIRS = [
    Path("content/external"),
    Path("content/images"),
]

MD_EXTENSIONS = {".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}
SIDECAR_EXTENSIONS = {".json"}
ALL_EXTENSIONS = MD_EXTENSIONS | IMAGE_EXTENSIONS | SIDECAR_EXTENSIONS

DEBOUNCE_SECONDS = 2.0


class ContentChangeHandler(FileSystemEventHandler):
    """Handles filesystem events, filters by extension, debounces, and publishes to Kafka."""

    def __init__(self, producer: KafkaProducer, topic: str):
        super().__init__()
        self.producer = producer
        self.topic = topic
        self._last_seen: dict[str, float] = {}
        self._lock = Lock()

    def _should_handle(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        if ext not in ALL_EXTENSIONS:
            return False
        parent = Path(path).parent.name
        if ext in MD_EXTENSIONS and parent != "external":
            return False
        return True

    def _is_debounced(self, path: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last_seen.get(path, 0.0)
            if now - last < DEBOUNCE_SECONDS:
                return True
            self._last_seen[path] = now
            return False

    def _publish(self, path: str, event_type: str) -> None:
        payload = {
            "path": path,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.producer.send(
            self.topic,
            value=json.dumps(payload).encode("utf-8"),
            key=path.encode("utf-8"),
        )
        self.producer.flush()
        logger.info("Published %s event for %s", event_type, path)

    def on_created(self, event):
        if event.is_directory:
            return
        if not self._should_handle(event.src_path):
            return
        if self._is_debounced(event.src_path):
            return
        self._publish(event.src_path, "created")

    def on_modified(self, event):
        if event.is_directory:
            return
        if not self._should_handle(event.src_path):
            return
        if self._is_debounced(event.src_path):
            return
        self._publish(event.src_path, "modified")


def create_producer() -> KafkaProducer:
    logger.info("Connecting to Kafka at %s", KAFKA_BOOTSTRAP)
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        acks="all",
        retries=3,
    )


def run() -> None:
    producer = create_producer()
    handler = ContentChangeHandler(producer, KAFKA_TOPIC)
    observer = Observer()

    for watch_dir in WATCH_DIRS:
        abs_dir = Path.cwd() / watch_dir
        if not abs_dir.exists():
            logger.warning("Watch directory does not exist, creating: %s", abs_dir)
            abs_dir.mkdir(parents=True, exist_ok=True)
        observer.schedule(handler, str(abs_dir), recursive=False)
        logger.info("Watching %s", abs_dir)

    shutdown = False

    def _signal_handler(sig, frame):
        nonlocal shutdown
        shutdown = True
        logger.info("Shutdown signal received")

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    observer.start()
    logger.info("File watcher started — publishing to topic '%s'", KAFKA_TOPIC)

    try:
        while not shutdown:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
        producer.close()
        logger.info("File watcher stopped")


if __name__ == "__main__":
    run()
