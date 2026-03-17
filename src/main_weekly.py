"""
Weekly orchestrator — runs on Sunday at 03:00 NL time.

Steps:
1. Load LEGO set catalog
2. Scrape Vinted (NL + BE + DE) for all sets
3. Calculate price statistics per condition category
4. Update price history for charts
5. Save to data/vinted_prices.json and data/vinted_price_history.json
"""

import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

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
        from src.scrapers.vinted_lego import load_prices
        prices = load_prices()
        if prices:
            print(f"[Weekly] Loaded existing price data from {prices.get('scraped_at', 'unknown')}")
        return

    from src.scrapers.vinted_lego import scrape_all_sets
    print("[Weekly] Scraping Vinted NL/BE/DE for all sets...")
    results = scrape_all_sets(lego_sets)

    total_listings = sum(
        set_data["all"].listing_count
        for set_data in results.values()
        if isinstance(set_data, dict) and "all" in set_data
    )

    elapsed = (datetime.now() - start).seconds
    print(f"[Weekly] Completed in {elapsed}s — {len(results)} sets scraped, {total_listings} total Vinted listings")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LEGO Circulair Trader — Weekly Vinted Run")
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
