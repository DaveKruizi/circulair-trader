"""
Daily orchestrator — runs at 04:00 NL time.

Steps:
1. Load LEGO set catalog (vehicle sets only)
2. Scrape Marktplaats for all sets (set-number-only, lifecycle tracking)
3. Compute price intelligence for Marktplaats from SQLite data
4. Generate interactive dashboard (output/index.html + output/data/dashboard_data.json)
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


def run_daily(dry_run: bool = False) -> None:
    start = datetime.now()
    print(f"[Daily] Starting at {start.strftime('%Y-%m-%d %H:%M:%S')}")

    # Step 0: Weekly retail price refresh (max 1x per 7 dagen)
    try:
        from src.retail_prices import run_update, should_run_today
        raw = json.loads(LEGO_SETS_PATH.read_text())
        if should_run_today(raw):
            print("[Daily] Retailprijzen bijwerken via lego.com (maandelijks)...")
            result = run_update(dry_run=dry_run)
            print(
                f"[Daily] Retailprijzen: {len(result['updated'])} gewijzigd, "
                f"{len(result['unchanged'])} ongewijzigd, "
                f"{len(result['skipped'])} overgeslagen"
            )
        else:
            print("[Daily] Retailprijzen: recent bijgewerkt, overgeslagen")
    except Exception as e:
        print(f"[Daily] Retailprijsupdate mislukt (wordt overgeslagen): {e}")

    lego_sets = load_lego_sets()
    print(f"[Daily] Loaded {len(lego_sets)} LEGO sets from catalog")

    # Step 1: Scrape Marktplaats
    if dry_run:
        print("[Daily] DRY RUN: skipping Marktplaats scrape, loading existing data")
        from src.scrapers.marktplaats_lego import load_deals_data
        marktplaats_data = load_deals_data()
        scraped_at = marktplaats_data.get("scraped_at", datetime.now().isoformat())
    else:
        from src.scrapers.marktplaats_lego import scrape_all_sets, load_deals_data
        print("[Daily] Scraping Marktplaats...")
        scrape_all_sets(lego_sets)
        marktplaats_data = load_deals_data()
        scraped_at = marktplaats_data.get("scraped_at", datetime.now().isoformat())

    total_mp = sum(len(v) for v in marktplaats_data.get("sets", {}).values())
    print(f"[Daily] Marktplaats: {total_mp} valid listings found")

    # Step 2: Compute price intelligence for all platforms
    # (Vinted data is already in SQLite from the earlier Vinted workflow run)
    from src.analysis.price_intelligence import compute_all_sets
    print("[Daily] Computing price intelligence for all platforms...")
    compute_all_sets(lego_sets, ["marktplaats", "vinted_nl"])

    # Step 3: Rejection summary
    from src import db
    summary = db.get_rejection_summary(days=1)
    if summary:
        print(f"[Daily] Auto-rejections today: {dict(summary)}")

    # Step 4: Generate dashboard
    from src.dashboard.generator import generate_dashboard
    print("[Daily] Generating interactive dashboard...")
    generate_dashboard(
        lego_sets=lego_sets,
        marktplaats_deals=marktplaats_data,
        scraped_at=scraped_at,
    )

    elapsed = (datetime.now() - start).seconds
    print(f"[Daily] Completed in {elapsed}s")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LEGO Circulair Trader — Daily Run")
    parser.add_argument("--dry-run", action="store_true", help="Skip scraping, use cached data")
    args = parser.parse_args()

    try:
        run_daily(dry_run=args.dry_run)
    except Exception as e:
        print(f"[ERROR] Daily run failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
