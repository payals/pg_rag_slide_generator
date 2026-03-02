"""
Run Report CLI - Pretty-prints a deck generation report.

Shows "Postgres as control plane" evidence:
- Deck summary and coverage
- Cost tracking (tokens + estimated USD)
- Gate statistics (pass/fail per gate type)
- Top failure reasons and sources
- Per-slide details

Usage:
    python -m src.run_report --deck-id <uuid>
    python -m src.run_report --deck-id <uuid> --json
    python -m src.run_report --deck-id <uuid> --verbose
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Optional
from uuid import UUID

from dotenv import load_dotenv

# Load environment
load_dotenv()

# Conditional rich import
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from src.db import init_pool, close_pool, get_connection
from src.mcp_client import tool_call, init_mcp_client, close_mcp_client

logger = logging.getLogger(__name__)


# =============================================================================
# DATA FETCHING
# =============================================================================

async def fetch_gate_failures(deck_id: UUID) -> list[dict]:
    """Fetch top failure reasons from v_gate_failures."""
    try:
        async with get_connection() as conn:
            rows = await conn.fetch("""
                SELECT gate_name, reason, occurrence_count
                FROM v_gate_failures WHERE deck_id = $1
                ORDER BY occurrence_count DESC LIMIT 10
            """, deck_id)
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Could not fetch gate failures: {e}")
        return []


async def fetch_top_sources(deck_id: UUID) -> list[dict]:
    """Fetch most-cited sources from v_top_sources."""
    try:
        async with get_connection() as conn:
            rows = await conn.fetch("""
                SELECT doc_title, citation_count
                FROM v_top_sources WHERE deck_id = $1
                ORDER BY citation_count DESC LIMIT 10
            """, deck_id)
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Could not fetch top sources: {e}")
        return []


async def build_full_report(deck_id: UUID) -> dict:
    """Build a comprehensive report by combining fn_get_run_report with supplemental queries."""
    report = await tool_call("mcp_get_run_report", deck_id=str(deck_id))
    report["gate_failures"] = await fetch_gate_failures(deck_id)
    report["top_sources"] = await fetch_top_sources(deck_id)
    return report


# =============================================================================
# PLAIN TEXT FORMATTING (fallback when rich not available)
# =============================================================================

def format_plain(report: dict, verbose: bool = False) -> str:
    """Format report as plain text."""
    lines = []
    
    lines.append("=" * 60)
    lines.append("  DECK GENERATION REPORT")
    lines.append("=" * 60)
    
    # Header
    lines.append(f"\n  Deck ID:      {report.get('deck_id', 'N/A')}")
    lines.append(f"  Topic:        {report.get('topic', 'N/A')}")
    lines.append(f"  Generated:    {report.get('generated_at', 'N/A')}")
    
    # Summary
    summary = report.get("summary", {})
    lines.append(f"\n--- Summary ---")
    lines.append(f"  Slides:       {summary.get('total_slides', 0)} / {summary.get('target_slides', '?')}")
    lines.append(f"  Coverage:     {summary.get('coverage_pct', 0):.1f}%")
    lines.append(f"  Total retries: {summary.get('total_retries', 0)}")
    
    # Cost
    cost = report.get("orchestrator_metrics", {}).get("cost", {})
    if cost:
        lines.append(f"\n--- Cost ---")
        lines.append(f"  Prompt tokens:     {cost.get('prompt_tokens', 0):,}")
        lines.append(f"  Completion tokens: {cost.get('completion_tokens', 0):,}")
        lines.append(f"  Embedding tokens:  {cost.get('embedding_tokens', 0):,}")
        lines.append(f"  Estimated cost:    ${cost.get('estimated_cost_usd', 0):.4f}")
    
    # Coverage
    coverage = report.get("coverage", {})
    if coverage:
        lines.append(f"\n--- Coverage ---")
        covered = coverage.get("covered", [])
        missing = coverage.get("missing", [])
        if covered:
            lines.append(f"  Covered:  {', '.join(covered)}")
        if missing:
            lines.append(f"  Missing:  {', '.join(missing)}")
    
    # Gate Statistics
    gate_summary = report.get("gate_summary", {})
    if gate_summary:
        lines.append(f"\n--- Gate Statistics ---")
        for gate_name, stats in gate_summary.items():
            pass_count = stats.get("pass", 0)
            fail_count = stats.get("fail", 0)
            lines.append(f"  {gate_name:<20s}  pass={pass_count}  fail={fail_count}")
    
    # Top Failure Reasons
    failures = report.get("gate_failures", [])
    if failures:
        lines.append(f"\n--- Top Failure Reasons ---")
        for f in failures[:5]:
            lines.append(f"  [{f.get('gate_name', '')}] {f.get('reason', '')} (x{f.get('occurrence_count', 0)})")
    
    # Top Sources
    sources = report.get("top_sources", [])
    if sources:
        lines.append(f"\n--- Top Sources ---")
        for s in sources[:5]:
            lines.append(f"  {s.get('doc_title', 'Unknown')}: {s.get('citation_count', 0)} citations")
    
    # Per-slide details (verbose only)
    if verbose:
        slides = report.get("slides", [])
        if slides:
            lines.append(f"\n--- Per-Slide Details ---")
            for slide in slides:
                lines.append(f"\n  Slide {slide.get('slide_no', '?')}: {slide.get('intent', '?')}")
                lines.append(f"    Title: {slide.get('title', 'N/A')}")
                lines.append(f"    Retries: {slide.get('retry_count', 0)}")
    
    # Fallback status
    metrics = report.get("orchestrator_metrics", {})
    if metrics.get("fallback_triggered"):
        lines.append(f"\n  *** FALLBACK TRIGGERED ***")
        lines.append(f"  Failed intents: {metrics.get('failed_intents', [])}")
        lines.append(f"  Abandoned intents: {metrics.get('abandoned_intents', [])}")
    
    lines.append("\n" + "=" * 60)
    
    return "\n".join(lines)


# =============================================================================
# RICH FORMATTING
# =============================================================================

def format_rich(report: dict, verbose: bool = False) -> None:
    """Format report using Rich for beautiful terminal output."""
    console = Console()
    
    # Header
    console.print(Panel.fit(
        f"[bold cyan]Deck ID:[/] {report.get('deck_id', 'N/A')}\n"
        f"[bold cyan]Topic:[/] {report.get('topic', 'N/A')}\n"
        f"[bold cyan]Generated:[/] {report.get('generated_at', 'N/A')}",
        title="[bold white]DECK GENERATION REPORT[/]",
        border_style="blue",
    ))
    
    # Summary
    summary = report.get("summary", {})
    slides_text = f"{summary.get('total_slides', 0)} / {summary.get('target_slides', '?')}"
    coverage_pct = summary.get("coverage_pct", 0)
    coverage_color = "green" if coverage_pct >= 80 else "yellow" if coverage_pct >= 50 else "red"
    
    console.print(f"\n[bold]Summary:[/]")
    console.print(f"  Slides: {slides_text}")
    console.print(f"  Coverage: [{coverage_color}]{coverage_pct:.1f}%[/{coverage_color}]")
    console.print(f"  Total retries: {summary.get('total_retries', 0)}")
    
    # Cost
    cost = report.get("orchestrator_metrics", {}).get("cost", {})
    if cost:
        cost_table = Table(title="Cost Tracking", show_header=True, header_style="bold magenta")
        cost_table.add_column("Metric", style="dim")
        cost_table.add_column("Value", justify="right")
        cost_table.add_row("Prompt tokens", f"{cost.get('prompt_tokens', 0):,}")
        cost_table.add_row("Completion tokens", f"{cost.get('completion_tokens', 0):,}")
        cost_table.add_row("Embedding tokens", f"{cost.get('embedding_tokens', 0):,}")
        cost_table.add_row("[bold]Estimated cost[/]", f"[bold]${cost.get('estimated_cost_usd', 0):.4f}[/]")
        console.print(cost_table)
    
    # Coverage
    coverage = report.get("coverage", {})
    covered = coverage.get("covered", [])
    missing = coverage.get("missing", [])
    if covered or missing:
        console.print(f"\n[bold]Coverage:[/]")
        if covered:
            console.print(f"  [green]Covered:[/] {', '.join(covered)}")
        if missing:
            console.print(f"  [red]Missing:[/] {', '.join(missing)}")
    
    # Gate Statistics
    gate_summary = report.get("gate_summary", {})
    if gate_summary:
        gate_table = Table(title="Gate Statistics", show_header=True, header_style="bold cyan")
        gate_table.add_column("Gate", style="dim")
        gate_table.add_column("Pass", justify="right", style="green")
        gate_table.add_column("Fail", justify="right", style="red")
        for gate_name, stats in gate_summary.items():
            gate_table.add_row(gate_name, str(stats.get("pass", 0)), str(stats.get("fail", 0)))
        console.print(gate_table)
    
    # Top Failure Reasons
    failures = report.get("gate_failures", [])
    if failures:
        fail_table = Table(title="Top Failure Reasons", show_header=True, header_style="bold red")
        fail_table.add_column("Gate")
        fail_table.add_column("Reason")
        fail_table.add_column("Count", justify="right")
        for f in failures[:5]:
            fail_table.add_row(f.get("gate_name", ""), f.get("reason", ""), str(f.get("occurrence_count", 0)))
        console.print(fail_table)
    
    # Top Sources
    sources = report.get("top_sources", [])
    if sources:
        src_table = Table(title="Top Sources", show_header=True, header_style="bold green")
        src_table.add_column("Document")
        src_table.add_column("Citations", justify="right")
        for s in sources[:5]:
            src_table.add_row(s.get("doc_title", "Unknown"), str(s.get("citation_count", 0)))
        console.print(src_table)
    
    # Per-slide details (verbose)
    if verbose:
        slides = report.get("slides", [])
        if slides:
            slide_table = Table(title="Per-Slide Details", show_header=True, header_style="bold white")
            slide_table.add_column("#", justify="right")
            slide_table.add_column("Intent")
            slide_table.add_column("Title")
            slide_table.add_column("Retries", justify="right")
            for slide in slides:
                slide_table.add_row(
                    str(slide.get("slide_no", "?")),
                    slide.get("intent", "?"),
                    slide.get("title", "N/A")[:40],
                    str(slide.get("retry_count", 0)),
                )
            console.print(slide_table)
    
    # Fallback status
    metrics = report.get("orchestrator_metrics", {})
    if metrics.get("fallback_triggered"):
        console.print(Panel(
            f"[bold red]Failed intents:[/] {metrics.get('failed_intents', [])}\n"
            f"[bold red]Abandoned intents:[/] {metrics.get('abandoned_intents', [])}",
            title="[bold red]FALLBACK TRIGGERED[/]",
            border_style="red",
        ))


# =============================================================================
# CLI
# =============================================================================

async def run_report(deck_id: str, output_json: bool = False, verbose: bool = False) -> dict:
    """Generate and display a run report for a deck."""
    await init_pool()
    await init_mcp_client()
    
    try:
        report = await build_full_report(UUID(deck_id))
        
        if output_json:
            print(json.dumps(report, indent=2, default=str))
        elif HAS_RICH:
            format_rich(report, verbose=verbose)
        else:
            print(format_plain(report, verbose=verbose))
        
        return report
    finally:
        await close_mcp_client()
        await close_pool()


def main():
    """CLI entry point for run report."""
    parser = argparse.ArgumentParser(
        description="Generate a deck generation run report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pretty-print report
  python -m src.run_report --deck-id <uuid>
  
  # Output as JSON
  python -m src.run_report --deck-id <uuid> --json
  
  # Verbose with per-slide details
  python -m src.run_report --deck-id <uuid> --verbose
        """
    )
    
    parser.add_argument(
        "--deck-id",
        type=str,
        required=True,
        help="UUID of the deck"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output raw JSON (for scripting/piping)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Include per-slide gate details"
    )
    
    args = parser.parse_args()
    
    try:
        UUID(args.deck_id)
    except ValueError:
        print(f"Error: Invalid deck ID: {args.deck_id}")
        sys.exit(1)
    
    asyncio.run(run_report(
        deck_id=args.deck_id,
        output_json=args.output_json,
        verbose=args.verbose,
    ))


if __name__ == "__main__":
    main()
