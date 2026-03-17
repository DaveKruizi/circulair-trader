"""
Daily orchestrator — runs at 04:00 NL time.

Steps:
1. Load LEGO set catalog
2. Scrape Marktplaats for all sets
3. Apply deal filters (3 rules)
4. Calculate margins using latest Vinted price data
5. Detect price changes (alert)
6. Generate dashboard HTML
7. Data committed to data/ branch by GitHub Actions
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

    # Step 1: Load catalog
    lego_sets = load_lego_sets()
    print(f"[Daily] Loaded {len(lego_sets)} LEGO sets from catalog")

    # Step 2: Scrape Marktplaats (skip in dry_run)
    if dry_run:
        print("[Daily] DRY RUN: skipping Marktplaats scrape, loading existing data")
        from src.scrapers.marktplaats_lego import load_deals_data
        raw_deals = load_deals_data()
    else:
        from src.scrapers.marktplaats_lego import scrape_all_sets
        print("[Daily] Scraping Marktplaats...")
        results = scrape_all_sets(lego_sets)
        from src.scrapers.marktplaats_lego import load_deals_data
        raw_deals = load_deals_data()

    # Step 3: Load Vinted price data (from last weekly run)
    from src.analysis.vinted_analyzer import load_prices, load_history, enrich_set_summary
    vinted_prices = load_prices()
    vinted_history = load_history()
    print(f"[Daily] Vinted price data: {'loaded' if vinted_prices else 'not yet available'}")

    # Step 4 & 5: Apply deal filters and calculate margins
    from src.analysis.deal_filter import filter_deals, evaluate_deal
    from src.analysis.margin_calculator import all_condition_margins

    sets_data = raw_deals.get("sets", {})
    enriched_sets: list[dict] = []
    total_deals = 0
    new_today = 0
    price_drops = 0

    for lego_set in lego_sets:
        set_number = lego_set["set_number"]
        listings = sets_data.get(set_number, [])

        # Filter to qualifying deals only
        qualified = filter_deals(listings, lego_set)

        # Enrich each deal with margin calculations
        set_vinted = vinted_prices.get("sets", {}).get(set_number)
        for deal in qualified:
            deal["margins"] = {
                cat: {
                    "expected_sell_price": m.expected_sell_price,
                    "net_profit": m.net_profit,
                    "margin_pct": m.margin_pct,
                    "is_viable": m.is_viable,
                    "sell_price_source": m.sell_price_source,
                }
                for cat, m in all_condition_margins(
                    deal.get("price", 0), set_vinted
                ).items()
            }
            if deal.get("is_new_today"):
                new_today += 1
            if deal.get("price_changed"):
                price_drops += 1

        total_deals += len(qualified)

        # Enrich set with Vinted data
        enriched = enrich_set_summary(lego_set, vinted_prices, vinted_history)
        enriched["deals"] = qualified
        enriched["deal_count"] = len(qualified)
        enriched_sets.append(enriched)

    # Sort sets: most deals first, then alphabetically
    enriched_sets.sort(key=lambda s: (-s["deal_count"], s["name"]))

    print(f"[Daily] Total qualifying deals: {total_deals}")
    print(f"[Daily] New today: {new_today}")
    print(f"[Daily] Price drops: {price_drops}")

    # Step 6: Generate dashboard
    from src.dashboard.generator import generate_dashboard
    generate_dashboard(
        sets=enriched_sets,
        scraped_at=raw_deals.get("scraped_at", datetime.now().isoformat()),
        total_deals=total_deals,
        new_today=new_today,
        price_drops=price_drops,
        vinted_prices_date=vinted_prices.get("scraped_at", ""),
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
