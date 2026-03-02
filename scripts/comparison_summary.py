"""
Comparison Summary — aggregate multi-run pairwise results.

Reads from the comparison_run table and produces majority-vote
summaries per axis with confidence indicators.

Usage:
    python scripts/comparison_summary.py                    # latest deck pair
    python scripts/comparison_summary.py --last 10          # last 10 runs
    python scripts/comparison_summary.py --raw X.html       # specific raw deck
    python scripts/comparison_summary.py --all              # global aggregate across all runs
    python scripts/comparison_summary.py --all --by-pair    # all runs, grouped per deck pair
"""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


AXES = [
    ("Specificity", "specificity"),
    ("Accuracy", "accuracy"),
    ("Repetition", "repetition"),
    ("Technical depth", "depth"),
    ("Code examples", "code_examples"),
    ("Formatting", "formatting"),
]

WINNER_MAP = {"a": "Baseline", "b": "Raw LLM", "tie": "Tie"}


def confidence_label(pct: float) -> str:
    if pct >= 1.0:
        return "unanimous"
    if pct > 0.75:
        return "strong"
    if pct > 0.5:
        return "weak"
    return "split"


def aggregate_axes(rows: list) -> dict:
    """Aggregate per-axis results across multiple runs."""
    axis_results = {key: [] for _, key in AXES}

    for row in rows:
        comparisons = row["comparisons"]
        if isinstance(comparisons, str):
            comparisons = json.loads(comparisons)
        for _, key in AXES:
            c = comparisons.get(key, {})
            winner = c.get("winner", "tie").lower().strip()
            margin = c.get("margin", "tie").lower().strip()
            if winner == "tie":
                margin = "tie"
            elif margin == "tie" and winner in ("a", "b"):
                margin = "slightly"
            axis_results[key].append({"winner": winner, "margin": margin})

    aggregated = {}
    for _, key in AXES:
        results = axis_results[key]
        winner_counts = Counter(r["winner"] for r in results)
        majority_winner, majority_count = winner_counts.most_common(1)[0]

        margins_for_winner = [r["margin"] for r in results if r["winner"] == majority_winner]
        margin_counts = Counter(margins_for_winner)
        consensus_margin = margin_counts.most_common(1)[0][0] if margins_for_winner else "tie"

        n = len(results)
        pct = majority_count / n
        aggregated[key] = {
            "winner": majority_winner,
            "margin": consensus_margin,
            "confidence": confidence_label(pct),
            "wins": majority_count,
            "total": n,
            "breakdown": dict(winner_counts),
        }

    return aggregated


def _print_axis_table(agg: dict, n: int, label: str):
    """Print the aggregated axis table with overall winner tally."""
    print(f"  AGGREGATED PAIRWISE ({label})")
    print(f"  {'':20} {'Winner':<12} {'Margin':<12} {'Confidence':<12} Wins")
    print(f"  {'─' * 20} {'─' * 12} {'─' * 12} {'─' * 12} {'─' * 6}")

    overall_baseline = 0
    overall_raw = 0
    overall_tie = 0

    for axis_label, key in AXES:
        a = agg[key]
        winner_display = WINNER_MAP.get(a["winner"], a["winner"].title())
        margin_display = a["margin"] if a["margin"] != "tie" else ""
        wins_display = f"{a['wins']}/{a['total']}"

        if a["winner"] == "a":
            overall_baseline += 1
        elif a["winner"] == "b":
            overall_raw += 1
        else:
            overall_tie += 1

        print(f"  {axis_label:<20} {winner_display:<12} {margin_display:<12} {a['confidence']:<12} {wins_display}")

    print(f"  {'─' * 20} {'─' * 12} {'─' * 12} {'─' * 12} {'─' * 6}")

    parts = []
    if overall_baseline:
        parts.append(f"Baseline wins {overall_baseline} {'axis' if overall_baseline == 1 else 'axes'}")
    if overall_raw:
        parts.append(f"Raw LLM wins {overall_raw} {'axis' if overall_raw == 1 else 'axes'}")
    if overall_tie:
        parts.append(f"{overall_tie} tie{'s' if overall_tie > 1 else ''}")
    print(f"  Overall: {', '.join(parts)}")


def print_summary(rows: list, raw_file: str, ctrl_file: str):
    """Print a per-pair summary."""
    n = len(rows)
    W = 76
    SEP = "─" * W

    print(f"\n  {SEP}")
    print(f"  Comparison Summary: {n} run{'s' if n != 1 else ''}")
    print(f"  {SEP}")
    print(f"  Raw LLM:       {raw_file}")
    print(f"  Control Plane: {ctrl_file}")
    print()

    first = rows[0]
    tfidf = first["tfidf_coverage"]
    sem = first["semantic_sim"]
    v_shared = first["vocab_shared"]
    v_base = first["vocab_baseline"]

    print(f"  DETERMINISTIC METRICS (identical across runs)")
    print(f"  {'─' * 50}")
    if tfidf is not None:
        print(f"  TF-IDF coverage:       {tfidf:.0%}")
    if sem is not None:
        print(f"  Semantic similarity:   {sem:.2f}")
    if v_shared is not None and v_base is not None:
        print(f"  Technical vocabulary:  {v_shared} / {v_base}")
    print()

    agg = aggregate_axes(rows)
    _print_axis_table(agg, n, f"majority vote across {n} runs")
    print(f"  {SEP}\n")


def print_global_summary(all_rows: list, pair_count: int):
    """Print a single global aggregate across all runs regardless of deck pair."""
    n = len(all_rows)
    W = 76
    SEP = "─" * W

    print(f"\n  {SEP}")
    print(f"  Global Comparison Summary")
    print(f"  {n} runs across {pair_count} deck pair{'s' if pair_count != 1 else ''}")
    print(f"  {SEP}")
    print()

    tfidf_vals = [r["tfidf_coverage"] for r in all_rows if r["tfidf_coverage"] is not None]
    sem_vals = [r["semantic_sim"] for r in all_rows if r["semantic_sim"] is not None]
    shared_vals = [r["vocab_shared"] for r in all_rows if r["vocab_shared"] is not None]
    base_vals = [r["vocab_baseline"] for r in all_rows if r["vocab_baseline"] is not None]

    print(f"  DETERMINISTIC METRICS (averaged across {pair_count} pairs)")
    print(f"  {'─' * 50}")
    if tfidf_vals:
        avg_tfidf = sum(tfidf_vals) / len(tfidf_vals)
        print(f"  TF-IDF coverage:       {avg_tfidf:.0%}  (range: {min(tfidf_vals):.0%}–{max(tfidf_vals):.0%})")
    if sem_vals:
        avg_sem = sum(sem_vals) / len(sem_vals)
        print(f"  Semantic similarity:   {avg_sem:.2f}  (range: {min(sem_vals):.2f}–{max(sem_vals):.2f})")
    if shared_vals and base_vals:
        avg_shared = sum(shared_vals) / len(shared_vals)
        avg_base = sum(base_vals) / len(base_vals)
        print(f"  Technical vocabulary:  {avg_shared:.0f} / {avg_base:.0f}  (avg)")
    print()

    agg = aggregate_axes(all_rows)
    _print_axis_table(agg, n, f"majority vote across {n} runs, {pair_count} pairs")
    print(f"  {SEP}\n")


async def fetch_rows(args) -> tuple[list, list]:
    """Fetch rows. Returns (all_rows, grouped_pairs).

    grouped_pairs is [(raw_file, ctrl_file, rows), ...].
    all_rows is the flat list of every row (for global aggregate).
    """
    import asyncpg

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    conn = await asyncpg.connect(db_url)
    try:
        if args.raw:
            raw_name = Path(args.raw).name
            rows = await conn.fetch(
                "SELECT * FROM comparison_run WHERE raw_deck_file = $1 ORDER BY created_at DESC",
                raw_name,
            )
        elif args.ctrl:
            ctrl_name = Path(args.ctrl).name
            rows = await conn.fetch(
                "SELECT * FROM comparison_run WHERE ctrl_deck_file = $1 ORDER BY created_at DESC",
                ctrl_name,
            )
        elif args.all:
            rows = await conn.fetch("SELECT * FROM comparison_run ORDER BY created_at DESC")
        else:
            limit = args.last if args.last else None
            if limit:
                rows = await conn.fetch(
                    "SELECT * FROM comparison_run ORDER BY created_at DESC LIMIT $1", limit
                )
            else:
                latest = await conn.fetchrow(
                    "SELECT raw_deck_file, ctrl_deck_file FROM comparison_run ORDER BY created_at DESC LIMIT 1"
                )
                if not latest:
                    print("No comparison runs found. Run: python scripts/compare_decks.py --analyze")
                    return [], []
                rows = await conn.fetch(
                    "SELECT * FROM comparison_run WHERE raw_deck_file = $1 AND ctrl_deck_file = $2 ORDER BY created_at DESC",
                    latest["raw_deck_file"], latest["ctrl_deck_file"],
                )
    finally:
        await conn.close()

    if not rows:
        print("No comparison runs found matching the filter.")
        return [], []

    groups = {}
    for r in rows:
        key = (r["raw_deck_file"], r["ctrl_deck_file"])
        groups.setdefault(key, []).append(r)

    grouped = [(k[0], k[1], v) for k, v in groups.items()]
    return list(rows), grouped


def main():
    parser = argparse.ArgumentParser(description="Aggregate multi-run comparison results")
    parser.add_argument("--raw", type=str, default=None, help="Filter by raw deck filename")
    parser.add_argument("--ctrl", type=str, default=None, help="Filter by control deck filename")
    parser.add_argument("--last", type=int, default=None, help="Last N runs (most recent)")
    parser.add_argument("--all", action="store_true", help="Global aggregate across all runs and deck pairs")
    parser.add_argument("--by-pair", action="store_true", help="With --all: also show per-pair breakdowns")
    args = parser.parse_args()

    all_rows, groups = asyncio.run(fetch_rows(args))

    if not all_rows:
        return

    if args.all and not args.by_pair:
        print_global_summary(all_rows, len(groups))
    elif args.all and args.by_pair:
        print_global_summary(all_rows, len(groups))
        print("  Per-pair breakdowns:\n")
        for raw_file, ctrl_file, rows in groups:
            print_summary(rows, raw_file, ctrl_file)
    else:
        for raw_file, ctrl_file, rows in groups:
            print_summary(rows, raw_file, ctrl_file)


if __name__ == "__main__":
    main()
