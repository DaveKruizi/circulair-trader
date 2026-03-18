"""
Dagelijkse Vinted scraper — draait om 02:00 UTC (03:00 NL), vóór de Marktplaats run.

Steps:
1. Load LEGO set catalog (vehicle sets only)
2. Scrape Vinted NL for all sets (set-number-only search, lifecycle tracking)
3. Compute price intelligence (sell_price_fast, sell_price_realistic per platform/condition)
4. Log summary
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path
import json

LEGO_SETS_PATH = Path("data/lego_sets.json")


def load_lego_sets() -> list[dict]:
    try:
        data = json.loads(LEGO_SETS_PATH.read_text())
        return data["sets"]
    except Exception as e:
        print(f"[FATAL] Cannot load lego_sets.json: {e}")
        sys.exit(1)


def run_weekly(dry_run: bool = False) -> None:
    start = datetime.now()
    print(f"[Weekly] Starting at {start.strftime('%Y-%m-%d %H:%M:%S')}")

    lego_sets = load_lego_sets()
    print(f"[Weekly] Loaded {len(lego_sets)} LEGO sets from catalog")

    if dry_run:
        print("[Weekly] DRY RUN: skipping Vinted scrape")
        return

    # Step 1: Scrape Vinted
    from src.scrapers.vinted_lego import scrape_all_sets, VINTED_PLATFORMS
    print("[Weekly] Scraping Vinted NL for all sets...")
    results = scrape_all_sets(lego_sets)

    total = sum(
        len(listings)
        for set_data in results.values()
        for listings in set_data.values()
    )

    # Step 1b: Herclassificeer bestaande 'unknown' listings op basis van condition_raw
    from src import db
    from src.scrapers.vinted_lego import _classify_vinted_condition
    reclassified = db.reclassify_unknown_listings(
        lambda title, raw: _classify_vinted_condition(title, raw)
    )
    if reclassified:
        print(f"[Weekly] Herclassificeerd: {reclassified} 'unknown' listings bijgewerkt")

    # Step 2: Compute price intelligence from SQLite lifecycle data
    from src.analysis.price_intelligence import compute_all_sets
    platforms = [code for _, code in VINTED_PLATFORMS]
    print("[Weekly] Computing price intelligence...")
    compute_all_sets(lego_sets, platforms)

    # Step 3: Rejection summary
    summary = db.get_rejection_summary(days=1)
    if summary:
        print(f"[Weekly] Auto-rejections today: {dict(summary)}")

    elapsed = (datetime.now() - start).seconds
    print(f"[Weekly] Completed in {elapsed}s — {len(results)} sets, {total} valid listings")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LEGO Circulair Trader — Dagelijkse Vinted Run")
    parser.add_argument("--dry-run", action="store_true", help="Skip scraping")
    args = parser.parse_args()

    try:
        run_weekly(dry_run=args.dry_run)
    except Exception as e:
        print(f"[ERROR] Weekly run failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
