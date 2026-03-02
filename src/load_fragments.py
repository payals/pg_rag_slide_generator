"""Load HTML fragment files into slide_type_config.html_fragment.

Development workflow:
  1. Edit templates/fragments/{slide_type}.html in IDE
  2. Run: python -m src.load_fragments
  3. Restart app (or trigger reload) to pick up changes

Usage:
  python -m src.load_fragments          # Load all fragments
  python -m src.load_fragments code     # Load one fragment
  python -m src.load_fragments --check  # Verify file-DB parity (CI mode)
"""

import argparse
import asyncio
import sys
from pathlib import Path

FRAGMENTS_DIR = Path(__file__).parent.parent / "templates" / "fragments"


async def _get_slide_types() -> list[str]:
    """Load slide types from slide_type_config table (source of truth)."""
    from src.db import get_connection

    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT slide_type::text FROM slide_type_config ORDER BY slide_type"
        )
    return [row["slide_type"] for row in rows]


def read_fragment_file(slide_type: str) -> str:
    path = FRAGMENTS_DIR / f"{slide_type}.html"
    if not path.exists():
        raise FileNotFoundError(f"Fragment file not found: {path}")
    return path.read_text().strip()


async def load_fragment(slide_type: str) -> None:
    from src.db import get_connection

    content = read_fragment_file(slide_type)
    async with get_connection() as conn:
        result = await conn.execute(
            "UPDATE slide_type_config SET html_fragment = $1 WHERE slide_type = $2",
            content,
            slide_type,
        )
        if result == "UPDATE 0":
            print(f"  WARNING: No row for slide_type '{slide_type}'")
        else:
            print(f"  \u2713 {slide_type}: {len(content)} chars loaded")


async def load_all_fragments() -> None:
    from src.db import init_pool, close_pool

    await init_pool()
    slide_types = await _get_slide_types()
    print("Loading fragment files into slide_type_config.html_fragment:")
    for stype in slide_types:
        await load_fragment(stype)
    await close_pool()
    print("Done.")


async def check_parity() -> bool:
    from src.db import init_pool, close_pool, get_connection

    await init_pool()
    all_match = True
    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT slide_type::text, html_fragment FROM slide_type_config ORDER BY slide_type"
        )
    db_frags = {row["slide_type"]: row["html_fragment"] for row in rows}

    slide_types = list(db_frags.keys())
    for stype in slide_types:
        file_content = read_fragment_file(stype)
        db_content = (db_frags.get(stype) or "").strip()
        if file_content == db_content:
            print(f"  \u2713 {stype}: match")
        else:
            print(f"  \u2717 {stype}: MISMATCH (file={len(file_content)} chars, db={len(db_content)} chars)")
            all_match = False

    await close_pool()
    return all_match


async def main():
    from src.db import init_pool, close_pool

    parser = argparse.ArgumentParser(description="Load HTML fragments into DB")
    parser.add_argument(
        "slide_type", nargs="?", default=None,
        help="Specific slide type to load (default: all)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check file-DB parity without writing (CI mode)",
    )
    args = parser.parse_args()

    if args.check:
        ok = await check_parity()
        sys.exit(0 if ok else 1)

    if args.slide_type:
        await init_pool()
        slide_types = await _get_slide_types()
        if args.slide_type not in slide_types:
            print(f"Error: Unknown slide type '{args.slide_type}'. Valid: {slide_types}")
            sys.exit(1)
        await load_fragment(args.slide_type)
        await close_pool()
    else:
        await load_all_fragments()


if __name__ == "__main__":
    asyncio.run(main())
