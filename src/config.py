"""
Centralized configuration loaded from Postgres.

Replaces os.getenv() for all operational config (thresholds, model names,
limits, toggles).  Secrets and connection strings stay in .env.

Call order: init_pool() -> init_config() -> init_renderer()
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Module-level caches populated by init_config()
CONFIG: dict[str, Any] = {}
VALID_ENUMS: dict[str, frozenset[str]] = {}
VALID_GATE_NAMES: frozenset[str] = frozenset()


def _parse_value(raw: str, value_type: str) -> Any:
    """Convert a config row's string value to its declared Python type."""
    if value_type == "int":
        return int(raw)
    if value_type == "float":
        return float(raw)
    if value_type == "bool":
        return raw.lower() in ("true", "1", "yes")
    if value_type == "csv":
        return [s.strip() for s in raw.split(",") if s.strip()]
    return raw  # 'string' or unknown


async def load_config() -> dict[str, Any]:
    """Load all config rows from the Postgres config table."""
    global CONFIG
    from src.db import get_connection

    async with get_connection() as conn:
        rows = await conn.fetch("SELECT key, value, value_type FROM config")

    CONFIG.clear()
    for row in rows:
        CONFIG[row["key"]] = _parse_value(row["value"], row["value_type"])

    logger.info("Loaded %d config keys from Postgres", len(CONFIG))
    return CONFIG


async def load_enums() -> dict[str, frozenset[str]]:
    """Build valid-value sets from pg_enum for all custom types."""
    global VALID_ENUMS
    from src.db import get_connection

    type_names = (
        "slide_intent",
        "slide_type",
        "doc_type",
        "trust_level",
        "gate_decision",
        "image_style",
    )

    VALID_ENUMS.clear()
    async with get_connection() as conn:
        for tname in type_names:
            rows = await conn.fetch(
                "SELECT e.enumlabel "
                "FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = $1 "
                "ORDER BY e.enumsortorder",
                tname,
            )
            VALID_ENUMS[tname] = frozenset(r["enumlabel"] for r in rows)

    logger.info(
        "Loaded enums: %s",
        {k: len(v) for k, v in VALID_ENUMS.items()},
    )
    return VALID_ENUMS


async def load_gate_names() -> frozenset[str]:
    """Load canonical gate names from the config table."""
    global VALID_GATE_NAMES
    raw = CONFIG.get("valid_gate_names")
    if isinstance(raw, list):
        VALID_GATE_NAMES = frozenset(raw)
    elif isinstance(raw, str):
        VALID_GATE_NAMES = frozenset(s.strip() for s in raw.split(",") if s.strip())
    else:
        VALID_GATE_NAMES = frozenset()
    logger.info("Loaded %d gate names", len(VALID_GATE_NAMES))
    return VALID_GATE_NAMES


def get(key: str, default: Any = None) -> Any:
    """Read from loaded config cache."""
    return CONFIG.get(key, default)


async def init_config() -> None:
    """Must be called AFTER init_pool(), BEFORE init_renderer()."""
    await load_config()
    await load_enums()
    await load_gate_names()
