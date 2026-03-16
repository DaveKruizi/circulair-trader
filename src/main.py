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
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import OUTPUT_DIR, GITHUB_REPO, GITHUB_TOKEN
from src.scrapers.vinted import scrape_vinted_trends
from src.scrapers.marktplaats import scrape_marktplaats, BULK_SEARCH_TERMS
from src.scrapers.troostwijk import scrape_troostwijk
from src.scrapers.stocklear import scrape_stocklear
from src.scrapers.merkandi import scrape_merkandi
from src.scrapers.partijhandelaren import scrape_partijhandelaren
from src.scrapers.onlineveilingmeester import scrape_onlineveilingmeester
from src.analysis.opportunity_matcher import match_opportunities
from src.dashboard.generator import generate_dashboard


# ── Trend history ─────────────────────────────────────────────────
TREND_HISTORY_FILE = Path(OUTPUT_DIR) / "trend_history.json"
SEEN_DEALS_FILE = Path(OUTPUT_DIR) / "seen_deals.json"


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _update_trend_history(trends: list) -> dict:
    """Add today's trend data to history. Keep max 28 days."""
    history = _load_json(TREND_HISTORY_FILE)
    today = datetime.now().strftime("%Y-%m-%d")

    history[today] = {}
    for t in trends:
        history[today][t.search_term] = {
            "category": t.category,
            "avg_price": t.avg_price,
            "demand_score": t.demand_score,
            "listing_count": t.listing_count,
            "avg_favorites": t.avg_favorites,
        }

    # Keep only last 28 days
    sorted_dates = sorted(history.keys(), reverse=True)[:28]
    history = {d: history[d] for d in sorted_dates}

    _save_json(TREND_HISTORY_FILE, history)
    return history


def _update_seen_deals(opportunities: list) -> dict:
    """Track which deals we've seen before. Returns updated seen_deals dict."""
    seen = _load_json(SEEN_DEALS_FILE)
    today = datetime.now().strftime("%Y-%m-%d")

    for opp in opportunities:
        if opp.deal_id:
            if opp.deal_id not in seen:
                seen[opp.deal_id] = {
                    "first_seen": today,
                    "title": opp.title,
                    "url": opp.buy_url,
                    "price": opp.buy_price,
                }
            seen[opp.deal_id]["last_seen"] = today

    # Clean up deals older than 30 days
    cutoff = datetime.now()
    cleaned = {}
    for deal_id, info in seen.items():
        last = info.get("last_seen", "")
        try:
            days_ago = (cutoff - datetime.strptime(last, "%Y-%m-%d")).days
            if days_ago <= 30:
                cleaned[deal_id] = info
        except ValueError:
            cleaned[deal_id] = info

    _save_json(SEEN_DEALS_FILE, cleaned)
    return cleaned


# ── Feedback from GitHub Issues ───────────────────────────────────

def _fetch_feedback_from_issues() -> list[dict]:
    """Fetch negative feedback from GitHub Issues."""
    if not GITHUB_TOKEN:
        print("[Feedback] Geen GITHUB_TOKEN — feedback overslaan")
        return []

    try:
        import httpx
        resp = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues",
            params={"labels": "feedback-negative", "state": "open", "per_page": 50},
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[Feedback] GitHub API error: {resp.status_code}")
            return []

        feedback = []
        for issue in resp.json():
            body = issue.get("body", "")
            feedback.append({
                "title": issue.get("title", ""),
                "reason": body,
                "issue_number": issue.get("number"),
            })
        print(f"[Feedback] {len(feedback)} negatieve feedback items opgehaald")
        return feedback
    except Exception as e:
        print(f"[Feedback] Fout bij ophalen: {e}")
        return []


def _check_favorites_availability(favorites_issues: list[dict]):
    """Check if favorited items are still available, update Issues if not."""
    if not GITHUB_TOKEN:
        return

    try:
        import httpx
        client = httpx.Client(timeout=10)

        for fav in favorites_issues:
            url = fav.get("product_url", "")
            if not url:
                continue
            try:
                resp = client.head(url, follow_redirects=True)
                if resp.status_code == 404:
                    # Mark as uitverkocht
                    issue_num = fav.get("issue_number")
                    if issue_num:
                        client.post(
                            f"https://api.github.com/repos/{GITHUB_REPO}/issues/{issue_num}/labels",
                            json={"labels": ["uitverkocht"]},
                            headers={
                                "Authorization": f"token {GITHUB_TOKEN}",
                                "Accept": "application/vnd.github.v3+json",
                            },
                        )
            except Exception:
                continue
        client.close()
    except Exception as e:
        print(f"[Favorieten] Fout bij beschikbaarheidscheck: {e}")


def run_daily(dry_run: bool = False):
    """Execute the full daily research pipeline."""
    start = datetime.now()
    print(f"\n{'='*60}")
    print(f"Circulair Trader — Dagelijkse run gestart: {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # ── Load previous data ───────────────────────────────────────
    seen_deals = _load_json(SEEN_DEALS_FILE)

    # ── Fetch feedback from GitHub Issues ────────────────────────
    print("💬 Feedback ophalen uit GitHub Issues...")
    negative_feedback = _fetch_feedback_from_issues() if not dry_run else []

    # ── Step 1: Vinted trends ──────────────────────────────────────
    print("\n📊 Stap 1/4: Vinted trends ophalen...")
    try:
        trends = scrape_vinted_trends(max_per_term=20)
        print(f"   ✓ {len(trends)} trend categorieën gevonden")
        for t in trends[:3]:
            print(f"     • {t.search_term}: gem. €{t.avg_price:.2f}, demand {t.demand_score}/10")
    except Exception as e:
        print(f"   ✗ Fout bij Vinted scraping: {e}")
        trends = []

    # Save trend history
    trend_history = _update_trend_history(trends)
    print(f"   📈 Trendhistorie: {len(trend_history)} dagen opgeslagen")

    # ── Step 2: Buying platforms ───────────────────────────────────
    print("\n🔍 Stap 2/4: Inkoopplatforms scannen...")
    all_listings = []
    sources_scanned = []

    scrapers = [
        # Bulk-first: zoekt op brede partij/lot termen, filtert op quantity >= 2.
        # Onafhankelijk van Vinted trends — alles wat in bulk aangeboden wordt is interessant.
        ("Marktplaats", lambda: scrape_marktplaats(
            BULK_SEARCH_TERMS, max_price=3000, min_quantity=2
        )),
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
            negative_feedback=negative_feedback,
            seen_deals=seen_deals,
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

    # Update seen deals tracker
    seen_deals = _update_seen_deals(opportunities)

    # ── Step 4: Dashboard ──────────────────────────────────────────
    print("\n📱 Stap 4/4: Dashboard genereren...")
    try:
        dashboard_path = generate_dashboard(
            opportunities=opportunities,
            trends=trends,
            sources_scanned=sources_scanned,
            trend_history=trend_history,
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
        new_deals = [o for o in opportunities if o.is_new]
        print(f"Met >€10 winst: {len(viable)}")
        print(f"Nieuwe deals: {len(new_deals)}")
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
