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
DEAL_DISCOUNT_PCT = 20   # minimaal X% onder mediaan vraagprijs → deal
STEAL_DISCOUNT_PCT = 35  # ≥X% onder mediaan vraagprijs → steal
BCG_VELOCITY_THRESHOLD = 50   # hot_score >= 50 = hoge snelheid
BCG_VALUE_THRESHOLD = 1.15    # NIB p50 >= retail * 1.15 = waardestijging (NIB-modus)
BCG_CIB_SPREAD_THRESHOLD = 1.30  # NIB p50 >= CIB p50 * 1.30 = goede handelsmarge (CIB-modus)
BCG_RECENT_RETIRED_YEARS = 2  # ≤ N jaar retired = "recently retired"
BCG_RECENT_RETIRED_DEEP_DISCOUNT = 0.80  # >20% onder retail → toch Dog


def _p50s(platforms_data: dict, condition: str) -> list[float]:
    """Haal alle beschikbare p50-waarden op voor één conditie over alle platforms."""
    return [
        pd[condition]["p50"]
        for pd in platforms_data.values()
        if pd.get(condition, {}).get("p50") is not None
    ]


def _compute_hot_score_condition(platforms_data: dict, condition: str) -> int:
    """Score 0–100 voor één conditie (NIB of CIB) over alle platforms."""
    total_dis = 0
    total_act = 0
    for platform_data in platforms_data.values():
        intel = platform_data.get(condition, {})
        total_dis += intel.get("disappeared_7d", 0)
        total_act += intel.get("active_count", 0)
    pool = total_dis + total_act
    if pool == 0:
        return 0
    velocity = total_dis / pool
    druk = min(total_dis / max(total_act, 1), 2) / 2
    return min(round((0.6 * velocity + 0.4 * druk) * 100), 100)


def _compute_hot_score(platforms_data: dict) -> int:
    """Gecombineerde hot score over NIB + CIB (voor algemeen gebruik)."""
    total_dis = 0
    total_act = 0
    for condition in ("NIB", "CIB"):
        for platform_data in platforms_data.values():
            intel = platform_data.get(condition, {})
            total_dis += intel.get("disappeared_7d", 0)
            total_act += intel.get("active_count", 0)
    pool = total_dis + total_act
    if pool == 0:
        return 0
    velocity = total_dis / pool
    druk = min(total_dis / max(total_act, 1), 2) / 2
    return min(round((0.6 * velocity + 0.4 * druk) * 100), 100)


def _compute_retirement_indicator(lego_set: dict, platforms_data: dict, current_year: int) -> Optional[dict]:
    """
    Alleen voor retired sets: vergelijkt huidige NIB-mediaan (beide platforms)
    met de officiële retailprijs. Geeft richting, totaal percentage en CAGR terug.
    """
    if not lego_set.get("is_retired"):
        return None
    retail = lego_set.get("retail_price")
    if not retail:
        return None
    nib_p50s = _p50s(platforms_data, "NIB")
    if not nib_p50s:
        return None
    avg = sum(nib_p50s) / len(nib_p50s)
    pct = round((avg / retail - 1) * 100)

    # CAGR: jaarlijks geannualiseerd rendement t.o.v. retailprijs
    # Gebruik retired_year als startpunt (= laatste jaar te koop bij retail).
    # Fallback: release_year (conservatiever — overschat de periode).
    annual_return_pct = None
    retired_year = lego_set.get("retired_year")
    release_year = lego_set.get("release_year")
    base_year = retired_year or release_year
    if base_year:
        years = max(current_year - base_year, 0.5)
        annual_return_pct = round(((avg / retail) ** (1 / years) - 1) * 100, 1)

    if avg > retail * 1.05:
        return {"direction": "up", "pct": pct, "annual_return_pct": annual_return_pct}
    if avg < retail * 0.95:
        return {"direction": "down", "pct": abs(pct), "annual_return_pct": annual_return_pct}
    return {"direction": "stable", "pct": 0, "annual_return_pct": annual_return_pct}


def _recently_retired(lego_set: dict, current_year: int) -> bool:
    retired_year = lego_set.get("retired_year")
    return (
        lego_set.get("is_retired", False)
        and retired_year is not None
        and (current_year - retired_year) <= BCG_RECENT_RETIRED_YEARS
    )


def _compute_bcg_nib(lego_set: dict, platforms_data: dict, hot_score_nib: int, current_year: int) -> str:
    """
    BCG voor NIB (beleggingsstrategie: bewaren en waardeontwikkeling volgen).

    Waarde-as : NIB p50 >= retail * 1.15
    Snelheid  : NIB hot score >= 50

    Star       : snel + boven retail, óf recent retired + boven retail
    Cash Cow   : langzaam + boven retail (bewaren, gestaag rendement)
    Question Mark: onvoldoende data, recent retired zonder premium, actief/retiring_soon
    Dog        : langzaam + onder retail (met data); recent retired >20% onder retail
    """
    is_retired = lego_set.get("is_retired", False)
    if not is_retired:
        return "question_mark"

    recently_ret = _recently_retired(lego_set, current_year)
    high_velocity = hot_score_nib >= BCG_VELOCITY_THRESHOLD

    retail = lego_set.get("retail_price")
    nib_p50s = _p50s(platforms_data, "NIB")
    avg_p50 = sum(nib_p50s) / len(nib_p50s) if nib_p50s else None

    if nib_p50s and retail:
        high_value = avg_p50 >= retail * BCG_VALUE_THRESHOLD
    elif nib_p50s and not retail:
        ri = _compute_retirement_indicator(lego_set, platforms_data, current_year)
        high_value = ri is not None and ri.get("direction") == "up"
    else:
        high_value = False

    if (high_velocity and high_value) or (recently_ret and high_value):
        return "star"
    if not high_velocity and high_value:
        return "cash_cow"
    if high_velocity:
        return "question_mark"

    # Langzaam + lage waarde
    if not nib_p50s or hot_score_nib == 0:
        return "question_mark"
    if recently_ret:
        deep_discount = retail and avg_p50 is not None and avg_p50 < retail * BCG_RECENT_RETIRED_DEEP_DISCOUNT
        return "dog" if deep_discount else "question_mark"
    return "dog"


def _compute_bcg_cib(lego_set: dict, platforms_data: dict, hot_score_cib: int, current_year: int) -> str:
    """
    BCG voor CIB (handelsstrategie: actief kopen en snel doorverkopen).

    Marge-as  : NIB p50 >= CIB p50 * 1.30 (30% spread = goede flip-marge)
    Snelheid  : CIB hot score >= 50

    Star       : hoge CIB velocity + goede spread → actief handelen
    Question Mark: één as ontbreekt, recent retired, of actief/retiring_soon
    Dog        : lage velocity + dunne spread + voldoende data
    Cash Cow bestaat niet: CIB bewaar je niet.
    """
    is_retired = lego_set.get("is_retired", False)
    if not is_retired:
        return "question_mark"

    recently_ret = _recently_retired(lego_set, current_year)
    high_velocity = hot_score_cib >= BCG_VELOCITY_THRESHOLD

    nib_p50s = _p50s(platforms_data, "NIB")
    cib_p50s = _p50s(platforms_data, "CIB")

    if nib_p50s and cib_p50s:
        avg_nib = sum(nib_p50s) / len(nib_p50s)
        avg_cib = sum(cib_p50s) / len(cib_p50s)
        good_spread = avg_nib >= avg_cib * BCG_CIB_SPREAD_THRESHOLD
    else:
        good_spread = False

    no_data = not cib_p50s or hot_score_cib == 0

    if high_velocity and good_spread:
        return "star"
    if no_data or recently_ret:
        return "question_mark"
    if not high_velocity and not good_spread:
        return "dog"
    return "question_mark"


def _find_deals(
    platforms_data: dict, seller_lego_counts: dict, retail_price: float | None
) -> list[dict]:
    """
    Interessante Marktplaats-deals, gecategoriseerd als 'steal' of 'deal':
    - Steal: ≥STEAL_DISCOUNT_PCT% onder p50, OF NIB-prijs onder retailprijs terwijl p50 > retail
    - Deal: ≥DEAL_DISCOUNT_PCT% onder p50 (maar geen steal)
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

        deal_threshold = p50 * (1 - DEAL_DISCOUNT_PCT / 100)

        for listing in intel.get("listings", []):
            price = listing.get("price", 0)
            if not price:
                continue

            # NIB-prijs onder retail terwijl markt boven retail staat → steal-kandidaat
            nib_below_retail = (
                condition == "NIB"
                and retail_price is not None
                and price < retail_price
                and p50 > retail_price
            )

            if price > deal_threshold and not nib_below_retail:
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

            discount_pct = round((1 - price / p50) * 100)
            is_steal = discount_pct >= STEAL_DISCOUNT_PCT or nib_below_retail
            category = "steal" if is_steal else "deal"

            deals.append({
                **listing,
                "condition": condition,
                "p50": round(p50, 0),
                "discount_pct": discount_pct,
                "is_trader": is_trader,
                "seller_count": seller_count,
                "price_type": price_type,
                "category": category,
            })

    # Steals eerst, daarna deals; binnen categorie op korting aflopend
    return sorted(deals, key=lambda d: (d["category"] != "steal", -d["discount_pct"]))


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

    current_year = datetime.now().year

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

        # Indicatoren
        hot_score_nib = _compute_hot_score_condition(platforms_data, "NIB")
        hot_score_cib = _compute_hot_score_condition(platforms_data, "CIB")
        retirement_indicator = _compute_retirement_indicator(lego_set, platforms_data, current_year)
        deals = _find_deals(platforms_data, seller_lego_counts, lego_set.get("retail_price"))
        bcg_nib = _compute_bcg_nib(lego_set, platforms_data, hot_score_nib, current_year)
        bcg_cib = _compute_bcg_cib(lego_set, platforms_data, hot_score_cib, current_year)

        sets_out.append({
            "set_number": set_number,
            "name": lego_set["name"],
            "theme": lego_set.get("theme", ""),
            "retail_price": retail_price,
            "market_value_new": lego_set.get("market_value_new"),
            "is_retired": lego_set.get("is_retired", False),
            "retiring_soon": lego_set.get("retiring_soon", False),
            "retired_year": lego_set.get("retired_year"),
            "release_year": lego_set.get("release_year"),
            "piece_count": lego_set.get("piece_count"),
            "image_url": lego_set.get("image_url", ""),
            "platforms": platforms_data,
            "price_history": history,
            "mp_listings": mp_listings[:15],
            "price_too_low_7d": ptl_by_set.get(set_number, []),
            "hot_score_nib": hot_score_nib,
            "hot_score_cib": hot_score_cib,
            "retirement_indicator": retirement_indicator,
            "deals": deals,
            "bcg_nib": bcg_nib,
            "bcg_cib": bcg_cib,
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
