"""
Circulair Trader — Daily Runner.

Run this script daily (via cron or schedule) to:
1. Scrape Vinted for trends
2. Scrape all buying platforms
3. Match and rank opportunities
4. Generate HTML dashboard

Usage:
    python src/main.py                    # Run once now
    python src/main.py --schedule         # Run on daily schedule (07:00)
    python src/main.py --dry-run          # Run without Claude API calls

Cron example (runs at 07:00 every day):
    0 7 * * * cd /path/to/circulair-trader && python src/main.py >> logs/daily.log 2>&1
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scrapers.vinted import scrape_vinted_trends
from src.scrapers.marktplaats import scrape_marktplaats
from src.scrapers.troostwijk import scrape_troostwijk
from src.scrapers.stocklear import scrape_stocklear
from src.scrapers.merkandi import scrape_merkandi
from src.scrapers.partijhandelaren import scrape_partijhandelaren
from src.scrapers.onlineveilingmeester import scrape_onlineveilingmeester
from src.analysis.opportunity_matcher import match_opportunities
from src.dashboard.generator import generate_dashboard


def run_daily(dry_run: bool = False):
    """Execute the full daily research pipeline."""
    start = datetime.now()
    print(f"\n{'='*60}")
    print(f"Circulair Trader — Dagelijkse run gestart: {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # ── Step 1: Vinted trends ──────────────────────────────────────
    print("📊 Stap 1/4: Vinted trends ophalen...")
    try:
        trends = scrape_vinted_trends(max_per_term=20)
        print(f"   ✓ {len(trends)} trend categorieën gevonden")
        for t in trends[:3]:
            print(f"     • {t.search_term}: gem. €{t.avg_price:.2f}, demand {t.demand_score}/10")
    except Exception as e:
        print(f"   ✗ Fout bij Vinted scraping: {e}")
        trends = []

    # ── Step 2: Buying platforms ───────────────────────────────────
    print("\n🔍 Stap 2/4: Inkoopplatforms scannen...")
    all_listings = []
    sources_scanned = []

    # Search terms based on top trends
    search_terms = [t.search_term for t in trends[:5]] if trends else [
        "vintage sieraden", "designer tas", "sneakers", "vintage kleding"
    ]

    scrapers = [
        ("Marktplaats", lambda: scrape_marktplaats(search_terms, max_price=50)),
        ("Troostwijk", lambda: scrape_troostwijk(max_current_bid=50)),
        ("Stocklear", scrape_stocklear),
        ("Merkandi", scrape_merkandi),
        ("PartijHandelaren", scrape_partijhandelaren),
        ("OnlineVeilingmeester", scrape_onlineveilingmeester),
    ]

    for name, scraper_fn in scrapers:
        try:
            results = scraper_fn()
            all_listings.extend(results)
            sources_scanned.append(name)
            print(f"   ✓ {name}: {len(results)} listings")
        except Exception as e:
            print(f"   ✗ {name}: fout — {e}")

    print(f"   Totaal: {len(all_listings)} listings van {len(sources_scanned)} bronnen")

    # ── Step 3: Match & rank ───────────────────────────────────────
    print("\n🧠 Stap 3/4: Opportunities matchen en scoren...")
    try:
        opportunities = match_opportunities(
            buying_listings=all_listings,
            vinted_trends=trends,
            enrich_with_claude=(not dry_run),
        )
        print(f"   ✓ {len(opportunities)} viable opportunities gevonden")
        if opportunities:
            best = opportunities[0]
            print(f"   Beste: '{best.title[:50]}' — €{best.net_profit:.2f} netto winst")
    except Exception as e:
        print(f"   ✗ Fout bij matching: {e}")
        import traceback
        traceback.print_exc()
        opportunities = []

    # ── Step 4: Dashboard ──────────────────────────────────────────
    print("\n📱 Stap 4/4: Dashboard genereren...")
    try:
        dashboard_path = generate_dashboard(
            opportunities=opportunities,
            trends=trends,
            sources_scanned=sources_scanned,
        )
        print(f"   ✓ Dashboard opgeslagen: {dashboard_path}")
    except Exception as e:
        print(f"   ✗ Fout bij dashboard generatie: {e}")
        dashboard_path = None

    # ── Summary ────────────────────────────────────────────────────
    elapsed = (datetime.now() - start).seconds
    print(f"\n{'='*60}")
    print(f"Run voltooid in {elapsed}s")
    print(f"Opportunities: {len(opportunities)}")
    if opportunities:
        viable = [o for o in opportunities if o.net_profit >= 10]
        print(f"Met >€10 winst: {len(viable)}")
    if dashboard_path:
        print(f"Dashboard: {dashboard_path}")
    print(f"{'='*60}\n")

    return opportunities, trends


def main():
    parser = argparse.ArgumentParser(description="Circulair Trader daily runner")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run on daily schedule at 07:00",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without Claude API calls (faster, no cost)",
    )
    args = parser.parse_args()

    if args.schedule:
        import schedule

        print("📅 Scheduled mode: dagelijkse run om 07:00")
        schedule.every().day.at("07:00").do(run_daily, dry_run=args.dry_run)

        # Also run immediately on start
        run_daily(dry_run=args.dry_run)

        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_daily(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
