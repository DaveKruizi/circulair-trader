"""
Dashboard generator for LEGO Circulair Trader.

Produces:
- output/data/dashboard_data.json  : all data consumed by the interactive JS dashboard
- output/index.html                : static shell that fetches the JSON and renders it
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("output")
DATA_OUTPUT_DIR = OUTPUT_DIR / "data"
TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"

ALL_PLATFORMS = ["vinted_nl", "marktplaats"]
PLATFORM_LABELS = {
    "vinted_nl": "Vinted NL",
    "marktplaats": "Marktplaats",
}


def build_dashboard_data(
    lego_sets: list[dict],
    marktplaats_deals: dict,
    scraped_at: str,
) -> dict:
    """
    Assemble all data needed by the interactive dashboard.
    Reads price intelligence from SQLite.
    """
    from src.analysis.price_intelligence import (
        compute_price_intelligence,
        get_price_history_for_dashboard,
    )
    from src import db
    db.init_db()

    # Fetch rejection data upfront so it's available during the sets loop
    rejection_summary = db.get_rejection_summary(days=7)
    price_too_low_details = db.get_price_too_low_details(days=7)
    ptl_by_set: dict[str, list] = {}
    for item in price_too_low_details:
        ptl_by_set.setdefault(item["set_number"], []).append(item)

    sets_out = []
    for lego_set in lego_sets:
        set_number = lego_set["set_number"]
        retail_price = lego_set.get("retail_price")

        # Price intelligence per platform per condition
        platforms_data: dict[str, dict] = {}
        for platform in ALL_PLATFORMS:
            platforms_data[platform] = {}
            for condition in ["NIB", "CIB"]:
                intel = compute_price_intelligence(set_number, platform, condition, retail_price)
                # Active listings for this platform+condition (for display)
                active = db.get_active_listings(set_number, platform, condition)
                intel["listings"] = [
                    {
                        "title": r["title"],
                        "price": r["price"],
                        "url": r["url"],
                        "image_url": r["image_url"],
                    }
                    for r in active[:20]  # max 20 per card
                ]
                platforms_data[platform][condition] = intel

            # Unknown-condition listings (no price intelligence, shown as-is)
            unknown_active = db.get_active_listings(set_number, platform, "unknown")
            platforms_data[platform]["unknown_listings"] = [
                {
                    "title": r["title"],
                    "price": r["price"],
                    "url": r["url"],
                    "image_url": r["image_url"],
                }
                for r in unknown_active[:20]
            ]

        # Price history for chart
        history = get_price_history_for_dashboard(set_number, ALL_PLATFORMS)

        # Marktplaats active listings (all conditions, for buying opps section)
        mp_listings = marktplaats_deals.get("sets", {}).get(set_number, [])

        sets_out.append({
            "set_number": set_number,
            "name": lego_set["name"],
            "theme": lego_set.get("theme", ""),
            "retail_price": retail_price,
            "market_value_new": lego_set.get("market_value_new"),
            "is_retired": lego_set.get("is_retired", False),
            "release_year": lego_set.get("release_year"),
            "piece_count": lego_set.get("piece_count"),
            "image_url": lego_set.get("image_url", ""),
            "platforms": platforms_data,
            "price_history": history,
            "mp_listings": mp_listings[:15],
            "price_too_low_7d": ptl_by_set.get(set_number, []),
        })

    total_sold = db.get_total_sold_count()

    return {
        "generated_at": datetime.now().isoformat(),
        "scraped_at": scraped_at,
        "platform_labels": PLATFORM_LABELS,
        "sets": sets_out,
        "rejection_summary_7d": rejection_summary,
        "total_sold_NIB": total_sold.get("NIB", 0),
        "total_sold_CIB": total_sold.get("CIB", 0),
    }


def generate_dashboard(
    lego_sets: list[dict],
    marktplaats_deals: dict,
    scraped_at: str,
) -> str:
    """Generate dashboard_data.json and copy index.html to output/."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build data
    data = build_dashboard_data(lego_sets, marktplaats_deals, scraped_at)

    # Write JSON
    json_path = DATA_OUTPUT_DIR / "dashboard_data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    # Copy static HTML shell
    html_dest = OUTPUT_DIR / "index.html"
    shutil.copy(str(TEMPLATE_PATH), str(html_dest))

    # Ensure .nojekyll for GitHub Pages
    (OUTPUT_DIR / ".nojekyll").touch()

    print(f"[Dashboard] Written to {html_dest}")
    print(f"[Dashboard] Data JSON: {json_path} ({json_path.stat().st_size // 1024}KB)")
    return str(html_dest)
