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
from typing import Optional

OUTPUT_DIR = Path("output")
DATA_OUTPUT_DIR = OUTPUT_DIR / "data"
TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"

ALL_PLATFORMS = ["vinted_nl", "marktplaats"]
PLATFORM_LABELS = {
    "vinted_nl": "Vinted NL",
    "marktplaats": "Marktplaats",
}

TRADER_THRESHOLD = 5  # meer dan N actieve LEGO-listings → LEGO-handelaar
DEAL_DISCOUNT_PCT = 20  # minimaal X% onder mediaan vraagprijs
BCG_VELOCITY_THRESHOLD = 50   # hot_score >= 50 = hoge snelheid
BCG_VALUE_THRESHOLD = 1.15    # NIB p50 >= retail * 1.15 = waardestijging


def _compute_hot_score(platforms_data: dict) -> int:
    """
    Score 0–100 op basis van verkoopsnelheid over beide platforms + NIB/CIB.
    sell_velocity  = verdwenen_7d / (verdwenen_7d + actief)   ← fractie die verkocht
    demand_druk    = min(verdwenen_7d / max(actief,1), 2) / 2  ← gecapped op 200%
    hot_score      = round((0.6 * velocity + 0.4 * druk) * 100)
    """
    total_dis = 0
    total_act = 0
    for platform_data in platforms_data.values():
        for condition in ("NIB", "CIB"):
            intel = platform_data.get(condition, {})
            total_dis += intel.get("disappeared_7d", 0)
            total_act += intel.get("active_count", 0)
    pool = total_dis + total_act
    if pool == 0:
        return 0
    velocity = total_dis / pool
    druk = min(total_dis / max(total_act, 1), 2) / 2
    return min(round((0.6 * velocity + 0.4 * druk) * 100), 100)


def _compute_retirement_indicator(lego_set: dict, platforms_data: dict) -> Optional[dict]:
    """
    Alleen voor retired sets: vergelijkt huidige NIB-mediaan (beide platforms)
    met de officiële retailprijs. Geeft richting + percentage terug.
    """
    if not lego_set.get("is_retired"):
        return None
    retail = lego_set.get("retail_price")
    if not retail:
        return None
    nib_p50s = [
        pd.get("NIB", {}).get("p50")
        for pd in platforms_data.values()
        if pd.get("NIB", {}).get("p50") is not None
    ]
    if not nib_p50s:
        return None
    avg = sum(nib_p50s) / len(nib_p50s)
    pct = round((avg / retail - 1) * 100)
    if avg > retail * 1.05:
        return {"direction": "up", "pct": pct}
    if avg < retail * 0.95:
        return {"direction": "down", "pct": abs(pct)}
    return {"direction": "stable", "pct": 0}


def _compute_bcg_category(lego_set: dict, platforms_data: dict, hot_score: int) -> str:
    """
    BCG Matrix voor LEGO-sets vanuit handelsperspectief.

    Snelheids-as  : hot_score >= BCG_VELOCITY_THRESHOLD → snel
    Waarde-as     : gemiddeld NIB p50 >= retail * BCG_VALUE_THRESHOLD → waardevol
                    Fallback (geen retailprijs): retirement_indicator 'up' → waardevol

    Star          : snel + waardevol   → kopen en snel doorverkopen
    Cash Cow      : langzaam + waardevol → kopen en vasthouden
    Question Mark : snel + niet waardevol (of onvoldoende data)
    Dog           : langzaam + niet waardevol → vermijden
    """
    high_velocity = hot_score >= BCG_VELOCITY_THRESHOLD

    retail = lego_set.get("retail_price")
    nib_p50s = [
        pd.get("NIB", {}).get("p50")
        for pd in platforms_data.values()
        if pd.get("NIB", {}).get("p50") is not None
    ]

    if nib_p50s and retail:
        avg_p50 = sum(nib_p50s) / len(nib_p50s)
        high_value = avg_p50 >= retail * BCG_VALUE_THRESHOLD
    elif nib_p50s and not retail:
        # Geen retailprijs → gebruik retirement indicator als proxy
        ri = _compute_retirement_indicator(lego_set, platforms_data)
        high_value = ri is not None and ri.get("direction") == "up"
    else:
        high_value = False

    if high_velocity and high_value:
        return "star"
    elif not high_velocity and high_value:
        return "cash_cow"
    elif high_velocity:
        return "question_mark"
    else:
        return "dog"


def _find_deals(platforms_data: dict, seller_lego_counts: dict) -> list[dict]:
    """
    Interessante Marktplaats-deals:
    - Vraagprijs ≥ DEAL_DISCOUNT_PCT% onder mediaan vraagprijs (per conditie)
    - Vaste prijs: OK ook als verkoper LEGO-handelaar is
    - Bieding: ALLEEN als verkoper GEEN LEGO-handelaar is (>TRADER_THRESHOLD listings)
    """
    deals = []
    mp_data = platforms_data.get("marktplaats", {})

    for condition in ("NIB", "CIB"):
        intel = mp_data.get(condition, {})
        p50 = intel.get("p50")
        if not p50:
            continue
        threshold = p50 * (1 - DEAL_DISCOUNT_PCT / 100)

        for listing in intel.get("listings", []):
            price = listing.get("price", 0)
            if not price or price > threshold:
                continue

            seller_name = listing.get("seller_name", "")
            price_type = listing.get("price_type", "fixed")

            # Brede LEGO-telling: eerst scrape-data (alle geziene listings),
            # fallback op DB-telling (alleen gevolgde sets)
            from src import db as _db
            seller_count = seller_lego_counts.get(seller_name) \
                or _db.get_seller_lego_count(seller_name)
            is_trader = seller_count > TRADER_THRESHOLD

            # Bieding van handelaar-verkoper: overslaan
            if price_type == "bidding" and is_trader:
                continue

            deals.append({
                **listing,
                "condition": condition,
                "p50": round(p50, 0),
                "discount_pct": round((1 - price / p50) * 100),
                "is_trader": is_trader,
                "seller_count": seller_count,
                "price_type": price_type,
            })

    return sorted(deals, key=lambda d: d["discount_pct"], reverse=True)


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

    # Brede LEGO-verkoperstelling uit de scrape-run
    seller_lego_counts: dict = marktplaats_deals.get("seller_lego_counts", {})

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
                        "is_reserved": bool(r.get("is_reserved", 0)),
                        "seller_name": r.get("seller_name", ""),
                        "price_type": r.get("price_type", "fixed"),
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

        # Nieuwe indicatoren
        hot_score = _compute_hot_score(platforms_data)
        retirement_indicator = _compute_retirement_indicator(lego_set, platforms_data)
        deals = _find_deals(platforms_data, seller_lego_counts)
        bcg_category = _compute_bcg_category(lego_set, platforms_data, hot_score)

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
            "hot_score": hot_score,
            "retirement_indicator": retirement_indicator,
            "deals": deals,
            "bcg_category": bcg_category,
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
