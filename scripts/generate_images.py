#!/usr/bin/env python3
"""
Main image generation orchestrator for Scale23x presentation.

Generates SVG images using Python templates and PNG images via Mermaid CLI.

Usage:
    # Generate all images
    python scripts/generate_images.py

    # Dry run (list what would be generated)
    python scripts/generate_images.py --dry-run

    # Generate specific image by name pattern
    python scripts/generate_images.py --name "gates_*"

    # Generate only SVGs or only Mermaid
    python scripts/generate_images.py --type svg
    python scripts/generate_images.py --type mermaid

    # Force regeneration (overwrite existing)
    python scripts/generate_images.py --force
"""

import argparse
import fnmatch
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.svg_lib.common import Palette
from scripts.svg_lib.diagrams import render_diagram
from scripts.svg_lib.charts import render_chart
from scripts.svg_lib.code_blocks import render_code_block
from scripts.svg_lib.decorative import render_decorative
from scripts.svg_lib.image_defs import IMAGE_DEFS, DIAGRAM, CHART, CODE, DECORATIVE

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = PROJECT_ROOT / "content" / "images"
MERMAID_DIR = PROJECT_ROOT / "scripts" / "mermaid_defs"
MERMAID_CONFIG = MERMAID_DIR / "mermaid_config.json"

# Mermaid CLI command — prefer npx for local install
MMDC_CMD = os.environ.get("MMDC_CMD", "npx mmdc")

# Output dimensions for Mermaid
MERMAID_WIDTH = 1600
MERMAID_HEIGHT = 900

# Existing images that should NOT be overwritten
EXISTING_IMAGES = {
    "comparison_01_feature_table",
    "comparison_02_scales_justice",
    "comparison_03_quadrant_matrix",
    "comparison_04_architecture_simplicity",
    "image_ingestion_pipeline_diagram",
    "problem_01_fragmented_architecture",
    "problem_03_crumbling_stack",
    "problem_04_venn_overlap",
    "title_01_elephant_circuit",
    "title_02_isometric_db_hub",
    "title_03_data_stream_elephant",
    "title_04_concentric_rings",
    "why_postgres_01_timeline",
    "why_postgres_02_fortress_elephant",
    "why_postgres_03_hub_spoke",
    "why_postgres_04_adoption_stats",
}

# Mermaid images (rendered from .mmd files)
MERMAID_IMAGES = {
    "architecture_02_data_flow",
    "architecture_04_c4_context",
    "gates_01_checkpoint_pipeline",
    "gates_02_decision_flowchart",
    "what_is_rag_01_three_step_flow",
    "what_is_rag_04_pipeline_vertical",
    "what_is_mcp_02_protocol_diagram",
    "what_we_built_03_journey_map",
}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Category → renderer dispatcher
# ---------------------------------------------------------------------------

CATEGORY_RENDERERS = {
    DIAGRAM: render_diagram,
    CHART: render_chart,
    CODE: render_code_block,
    DECORATIVE: render_decorative,
}


# ---------------------------------------------------------------------------
# SVG generation
# ---------------------------------------------------------------------------

def generate_svg_image(name: str, image_def: dict, output_dir: Path,
                       force: bool = False) -> Path | None:
    """
    Generate a single SVG image from its definition.

    Returns the output path, or None if skipped.
    """
    output_path = output_dir / f"{name}.svg"

    if output_path.exists() and not force:
        logger.info(f"  SKIP (exists): {output_path.name}")
        return None

    category = image_def["category"]
    template = image_def["template"]
    config = image_def.get("config", {})

    renderer = CATEGORY_RENDERERS.get(category)
    if not renderer:
        logger.error(f"  ERROR: Unknown category '{category}' for {name}")
        return None

    try:
        svg_content = renderer(template, config)
    except Exception as e:
        logger.error(f"  ERROR generating {name}: {e}")
        return None

    # Write SVG
    output_path.write_text(svg_content, encoding="utf-8")
    logger.info(f"  GENERATED: {output_path.name} ({len(svg_content):,} bytes)")
    return output_path


def convert_svg_to_png(svg_path: Path) -> Path | None:
    """
    Convert SVG to PNG using cairosvg (if available).

    Returns the PNG path or None if conversion not available.
    """
    try:
        import cairosvg
    except ImportError:
        logger.debug("cairosvg not installed, skipping PNG conversion")
        return None

    png_path = svg_path.with_suffix(".png")
    try:
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(png_path),
            output_width=1600,
            output_height=900,
        )
        logger.info(f"  CONVERTED: {png_path.name}")
        return png_path
    except Exception as e:
        logger.warning(f"  WARN: PNG conversion failed for {svg_path.name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Mermaid generation
# ---------------------------------------------------------------------------

def check_mermaid_cli() -> bool:
    """Check if Mermaid CLI (mmdc) is available."""
    # Handle "npx mmdc" as a compound command
    cmd_parts = MMDC_CMD.split()
    return shutil.which(cmd_parts[0]) is not None


def generate_mermaid_image(name: str, output_dir: Path,
                           force: bool = False) -> Path | None:
    """
    Generate a single Mermaid diagram from its .mmd file.

    Returns the output path, or None if skipped.
    """
    mmd_path = MERMAID_DIR / f"{name}.mmd"
    output_path = output_dir / f"{name}.png"

    if not mmd_path.exists():
        logger.error(f"  ERROR: Mermaid source not found: {mmd_path}")
        return None

    if output_path.exists() and not force:
        logger.info(f"  SKIP (exists): {output_path.name}")
        return None

    if not check_mermaid_cli():
        # Fall back to keeping the .mmd file — user can render later
        logger.warning(f"  WARN: mmdc not found. Copying {mmd_path.name} as reference.")
        # Generate a placeholder SVG instead
        return _generate_mermaid_placeholder(name, mmd_path, output_dir)

    cmd = MMDC_CMD.split() + [
        "-i", str(mmd_path),
        "-o", str(output_path),
        "-t", "dark",
        "-w", str(MERMAID_WIDTH),
        "-H", str(MERMAID_HEIGHT),
        "-b", "transparent",
    ]

    if MERMAID_CONFIG.exists():
        cmd.extend(["-c", str(MERMAID_CONFIG)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info(f"  GENERATED: {output_path.name} (mermaid)")
            return output_path
        else:
            logger.error(f"  ERROR: mmdc failed for {name}: {result.stderr}")
            return _generate_mermaid_placeholder(name, mmd_path, output_dir)
    except subprocess.TimeoutExpired:
        logger.error(f"  ERROR: mmdc timed out for {name}")
        return _generate_mermaid_placeholder(name, mmd_path, output_dir)
    except FileNotFoundError:
        logger.error(f"  ERROR: mmdc not found")
        return _generate_mermaid_placeholder(name, mmd_path, output_dir)


def _generate_mermaid_placeholder(name: str, mmd_path: Path,
                                  output_dir: Path) -> Path | None:
    """Generate a placeholder SVG for a Mermaid diagram when mmdc is not available.

    NOTE: Placeholder SVGs are skipped if a real PNG already exists for this
    diagram to avoid ingesting raw-code images alongside rendered ones.
    """
    # Skip placeholder if a real PNG already exists
    png_path = output_dir / f"{name}.png"
    if png_path.exists():
        logger.info(f"  SKIP PLACEHOLDER: {name}.png already exists — no SVG fallback needed")
        return None

    from scripts.svg_lib.common import svg_doc, text, rounded_rect

    # Read the .mmd source for display
    mmd_content = mmd_path.read_text(encoding="utf-8")
    lines = mmd_content.strip().split("\n")[:15]  # First 15 lines

    parts = []
    parts.append(text(600, 35, f"Mermaid Diagram: {name}", font_size=20, weight="700",
                      fill=Palette.TEXT_LIGHT))
    parts.append(text(600, 60, "(Render with: mmdc -i <input>.mmd -o <output>.png)",
                      font_size=12, fill=Palette.TEXT_MUTED))

    # Code block background
    parts.append(rounded_rect(60, 80, 1080, 550, Palette.BG_CARD,
                               stroke=Palette.BORDER, stroke_width=1, rx=8))

    for i, line_text in enumerate(lines):
        parts.append(
            f'<text x="80" y="{110 + i * 22}" font-size="13" '
            f'fill="{Palette.TEXT_LIGHT}" text-anchor="start" '
            f'dominant-baseline="middle" '
            f'font-family="\'JetBrains Mono\', monospace">'
            f'{__import__("html").escape(line_text)}</text>'
        )

    svg_content = svg_doc("\n".join(parts))
    output_path = output_dir / f"{name}.svg"
    output_path.write_text(svg_content, encoding="utf-8")
    logger.info(f"  PLACEHOLDER: {output_path.name} (mmdc not available)")
    return output_path


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def generate_all(
    name_pattern: str = "*",
    gen_type: str = "all",
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    Generate all images.

    Args:
        name_pattern: Glob pattern for image names (e.g., "gates_*")
        gen_type: "all", "svg", or "mermaid"
        dry_run: If True, list images without generating
        force: If True, overwrite existing images

    Returns:
        Report dict with counts
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "svg_generated": 0,
        "svg_skipped": 0,
        "svg_errors": 0,
        "mermaid_generated": 0,
        "mermaid_skipped": 0,
        "mermaid_errors": 0,
        "png_converted": 0,
        "total_existing": len(EXISTING_IMAGES),
        "details": [],
    }

    # -------------------------------------------------------
    # SVG images
    # -------------------------------------------------------
    if gen_type in ("all", "svg"):
        svg_names = sorted(IMAGE_DEFS.keys())
        matched = [n for n in svg_names if fnmatch.fnmatch(n, name_pattern)]

        logger.info(f"\n{'='*60}")
        logger.info(f"SVG IMAGES: {len(matched)} matched (of {len(svg_names)} total)")
        logger.info(f"{'='*60}")

        for name in matched:
            if name in EXISTING_IMAGES:
                logger.info(f"  SKIP (manual): {name}")
                report["svg_skipped"] += 1
                report["details"].append({"name": name, "status": "skip_manual", "type": "svg"})
                continue

            if dry_run:
                image_def = IMAGE_DEFS[name]
                logger.info(f"  WOULD GENERATE: {name} "
                           f"(category={image_def['category']}, template={image_def['template']})")
                report["details"].append({"name": name, "status": "dry_run", "type": "svg"})
                continue

            image_def = IMAGE_DEFS[name]
            result = generate_svg_image(name, image_def, OUTPUT_DIR, force=force)
            if result:
                report["svg_generated"] += 1
                report["details"].append({"name": name, "status": "generated", "type": "svg",
                                          "path": str(result)})
                # Try PNG conversion
                png = convert_svg_to_png(result)
                if png:
                    report["png_converted"] += 1
            else:
                report["svg_skipped"] += 1
                report["details"].append({"name": name, "status": "skipped", "type": "svg"})

    # -------------------------------------------------------
    # Mermaid images
    # -------------------------------------------------------
    if gen_type in ("all", "mermaid"):
        matched_mermaid = [n for n in sorted(MERMAID_IMAGES)
                          if fnmatch.fnmatch(n, name_pattern)]

        logger.info(f"\n{'='*60}")
        logger.info(f"MERMAID IMAGES: {len(matched_mermaid)} matched (of {len(MERMAID_IMAGES)} total)")
        logger.info(f"{'='*60}")

        for name in matched_mermaid:
            if name in EXISTING_IMAGES:
                logger.info(f"  SKIP (manual): {name}")
                report["mermaid_skipped"] += 1
                report["details"].append({"name": name, "status": "skip_manual", "type": "mermaid"})
                continue

            if dry_run:
                logger.info(f"  WOULD GENERATE: {name} (mermaid)")
                report["details"].append({"name": name, "status": "dry_run", "type": "mermaid"})
                continue

            result = generate_mermaid_image(name, OUTPUT_DIR, force=force)
            if result:
                report["mermaid_generated"] += 1
                report["details"].append({"name": name, "status": "generated", "type": "mermaid",
                                          "path": str(result)})
            else:
                report["mermaid_errors"] += 1
                report["details"].append({"name": name, "status": "error", "type": "mermaid"})

    return report


def print_report(report: dict) -> None:
    """Print a summary report."""
    print(f"\n{'='*60}")
    print("IMAGE GENERATION REPORT")
    print(f"{'='*60}")
    print(f"  SVG generated:     {report['svg_generated']}")
    print(f"  SVG skipped:       {report['svg_skipped']}")
    print(f"  SVG errors:        {report['svg_errors']}")
    print(f"  Mermaid generated: {report['mermaid_generated']}")
    print(f"  Mermaid skipped:   {report['mermaid_skipped']}")
    print(f"  Mermaid errors:    {report['mermaid_errors']}")
    print(f"  PNG converted:     {report['png_converted']}")
    print(f"  Pre-existing:      {report['total_existing']}")
    total_gen = report['svg_generated'] + report['mermaid_generated']
    total_all = total_gen + report['total_existing']
    print(f"  ─────────────────────────────")
    print(f"  Total generated:   {total_gen}")
    print(f"  Total images:      {total_all}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate presentation images (SVG + Mermaid)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/generate_images.py                     # Generate all
    python scripts/generate_images.py --dry-run            # Preview
    python scripts/generate_images.py --name "gates_*"     # Pattern match
    python scripts/generate_images.py --type svg           # SVGs only
    python scripts/generate_images.py --type mermaid       # Mermaid only
    python scripts/generate_images.py --force              # Overwrite existing
        """
    )
    parser.add_argument("--name", type=str, default="*",
                        help="Glob pattern for image names (default: '*')")
    parser.add_argument("--type", type=str, default="all",
                        choices=["all", "svg", "mermaid"],
                        help="Type of images to generate")
    parser.add_argument("--dry-run", action="store_true",
                        help="List images without generating")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing generated images")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(f"Image generator starting...")
    logger.info(f"  Output dir: {OUTPUT_DIR}")
    logger.info(f"  Pattern: {args.name}")
    logger.info(f"  Type: {args.type}")
    logger.info(f"  Force: {args.force}")
    logger.info(f"  Dry run: {args.dry_run}")

    report = generate_all(
        name_pattern=args.name,
        gen_type=args.type,
        dry_run=args.dry_run,
        force=args.force,
    )

    print_report(report)

    # Exit with error code if there were errors
    total_errors = report['svg_errors'] + report['mermaid_errors']
    if total_errors > 0:
        logger.error(f"{total_errors} errors occurred during generation")
        sys.exit(1)


if __name__ == "__main__":
    main()
