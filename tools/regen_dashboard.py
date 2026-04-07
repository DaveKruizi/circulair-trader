"""
Hergenereert het dashboard vanuit gecachte data — geen scraping, geen API-calls.
Gebruikt door de portfolio-manage workflow zodat retail-prijs-updates en scraping
de portfolio-verwerking niet kunnen blokkeren.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import db
from src.analysis.price_intelligence import compute_all_sets
from src.dashboard.generator import generate_dashboard
from src.scrapers.marktplaats_lego import load_deals_data

LEGO_SETS_PATH = Path("data/lego_sets.json")


def main() -> None:
    db.init_db()

    lego_sets = json.loads(LEGO_SETS_PATH.read_text(encoding="utf-8"))["sets"]
    print(f"[regen] {len(lego_sets)} sets geladen")

    # Prijsinformatie vanuit bestaande SQLite-data (geen web requests)
    compute_all_sets(lego_sets, ["marktplaats", "vinted_nl"])
    print("[regen] Prijsinformatie berekend")

    # Marktplaats-deals vanuit gecachte JSON (leeg als scraper nog nooit heeft gedraaid)
    mp_data = load_deals_data()
    scraped_at = mp_data.get("scraped_at", "")
    total = sum(len(v) for v in mp_data.get("sets", {}).values())
    print(f"[regen] Marktplaats data: {total} listings")

    generate_dashboard(
        lego_sets=lego_sets,
        marktplaats_deals=mp_data,
        scraped_at=scraped_at,
    )
    print("[regen] Dashboard klaar")


if __name__ == "__main__":
    main()
