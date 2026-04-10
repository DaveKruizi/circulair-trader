"""
Dashboard generator for LEGO Circulair Trader.

Produces:
- output/data/dashboard_data.json  : all data consumed by the interactive JS dashboard
- output/index.html                : static shell that fetches the JSON and renders it
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path("output")
DATA_OUTPUT_DIR = OUTPUT_DIR / "data"
TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"

ALL_PLATFORMS = ["vinted_nl", "marktplaats"]
CONDITIONS = ("NIB", "CIB")
PLATFORM_LABELS = {
    "vinted_nl": "Vinted NL",
    "marktplaats": "Marktplaats",
}

TRADER_THRESHOLD = 5       # meer dan N actieve LEGO-listings → LEGO-handelaar
DEAL_DISCOUNT_PCT = 20     # minimaal X% onder mediaan vraagprijs → deal
STEAL_DISCOUNT_PCT = 35    # ≥X% onder mediaan vraagprijs → steal
MIN_FLIP_MARGIN_EUR = 31   # p50 - aankoopprijs moet ≥ €31 (€25 netto + €6 verzending)
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


def _safe_avg(values: list[float]) -> Optional[float]:
    """Gemiddelde van een lijst, of None als de lijst leeg is."""
    return sum(values) / len(values) if values else None


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
    avg = _safe_avg(nib_p50s)
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
    avg_p50 = _safe_avg(nib_p50s)

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
    # Boven retail maar onder de 1.15× drempel → geen dog, hooguit question_mark
    if retail and avg_p50 is not None and avg_p50 >= retail:
        return "question_mark"
    return "dog"


def _compute_bcg_cib(lego_set: dict, platforms_data: dict, hot_score_cib: int, current_year: int) -> str:
    """
    BCG voor CIB (handelsstrategie: actief kopen en snel doorverkopen).

    Marge-as  : NIB p50 >= CIB p50 * 1.30 (30% spread = goede flip-marge)
    Snelheid  : CIB hot score >= 50

    Star       : hoge velocity + goede spread → snelle flip met marge
    Cash Cow   : hoge velocity + dunne spread → betrouwbaar, lage marge maar snel weg
    Question Mark: één as ontbreekt, recent retired, of actief/retiring_soon
    Dog        : lage velocity + dunne spread + voldoende data
    """
    is_retired = lego_set.get("is_retired", False)
    if not is_retired:
        return "question_mark"

    recently_ret = _recently_retired(lego_set, current_year)
    high_velocity = hot_score_cib >= BCG_VELOCITY_THRESHOLD

    nib_p50s = _p50s(platforms_data, "NIB")
    cib_p50s = _p50s(platforms_data, "CIB")

    if nib_p50s and cib_p50s:
        avg_nib = _safe_avg(nib_p50s)
        avg_cib = _safe_avg(cib_p50s)
        good_spread = avg_nib >= avg_cib * BCG_CIB_SPREAD_THRESHOLD
    else:
        good_spread = False

    no_data = not cib_p50s or hot_score_cib == 0

    if high_velocity and good_spread:
        return "star"
    if high_velocity and not good_spread:
        return "cash_cow"
    if no_data or recently_ret:
        return "question_mark"
    if not high_velocity and not good_spread:
        return "dog"
    return "question_mark"


def _compute_price_trend(set_number: str, condition: str) -> Optional[str]:
    """
    Vergelijk gemiddelde p50 van eerste helft vs tweede helft van de laatste 60 dagen.
    Geeft 'up', 'stable' of 'down' terug, of None bij onvoldoende data (< 10 snapshots).
    """
    from src import db

    all_prices: dict[str, list[float]] = {}
    for platform in ALL_PLATFORMS:
        for snap in db.get_price_history(set_number, platform, condition, limit=60):
            p50 = snap.get("p50_price")
            if p50 is None:
                continue
            all_prices.setdefault(snap["snapshot_date"], []).append(p50)

    if len(all_prices) < 10:
        return None

    p50s = [_safe_avg(v) for v in (all_prices[d] for d in sorted(all_prices))]
    half = len(p50s) // 2
    early = sum(p50s[:half]) / half
    late = sum(p50s[half:]) / (len(p50s) - half)

    if early <= 0:
        return None
    pct = (late / early - 1) * 100
    if pct > 5:
        return "up"
    if pct < -5:
        return "down"
    return "stable"


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
    from src import db as _db

    deals = []
    mp_data = platforms_data.get("marktplaats", {})

    for condition in CONDITIONS:
        intel = mp_data.get(condition, {})
        p50 = intel.get("p50")
        if not p50:
            continue

        deal_threshold = p50 * (1 - DEAL_DISCOUNT_PCT / 100)

        for listing in intel.get("listings_all", intel.get("listings", [])):
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

            # Brede LEGO-telling: eerst scrape-data, fallback op DB-telling
            seller_count = seller_lego_counts.get(seller_name) \
                or _db.get_seller_lego_count(seller_name)
            is_trader = seller_count > TRADER_THRESHOLD

            # Bieding van handelaar-verkoper: overslaan
            if price_type == "bidding" and is_trader:
                continue

            discount_pct = round((1 - price / p50) * 100)

            # Absolute minimummarge: moet ≥ €31 overhouden (€25 netto + €6 verzending)
            if p50 - price < MIN_FLIP_MARGIN_EUR:
                continue

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
            for condition in CONDITIONS:
                intel = compute_price_intelligence(set_number, platform, condition, retail_price)
                # Bewaar alle listings voor de deals-finder; bouw apart een display-versie
                # (max 20) voor de kaart — anders mist _find_deals() listings 21+.
                raw_listings = intel.pop("listings", [])
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
                    for r in raw_listings[:20]  # max 20 voor display
                ]
                # Deals-finder heeft alle listings nodig — aparte sleutel
                intel["listings_all"] = [
                    {
                        "price": r["price"],
                        "url": r["url"],
                        "image_url": r["image_url"],
                        "seller_name": r.get("seller_name", ""),
                        "price_type": r.get("price_type", "fixed"),
                        "title": r["title"],
                        "is_reserved": bool(r.get("is_reserved", 0)),
                    }
                    for r in raw_listings
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
        price_trend_nib = _compute_price_trend(set_number, "NIB")
        price_trend_cib = _compute_price_trend(set_number, "CIB")

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
            "price_trend_nib": price_trend_nib,
            "price_trend_cib": price_trend_cib,
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
    """Generate dashboard_data.json and index.html to output/."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build data
    data = build_dashboard_data(lego_sets, marktplaats_deals, scraped_at)

    # Write JSON
    json_path = DATA_OUTPUT_DIR / "dashboard_data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    # Portfolio: generate private JSON at token-based URL if PORTFOLIO_TOKEN is set
    portfolio_url = _build_portfolio_json(lego_sets, data)

    # Render HTML template (replace {{PORTFOLIO_URL}} placeholder)
    html_dest = OUTPUT_DIR / "index.html"
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = html.replace("{{PORTFOLIO_URL}}", portfolio_url)
    html_dest.write_text(html, encoding="utf-8")

    # Ensure .nojekyll for GitHub Pages
    (OUTPUT_DIR / ".nojekyll").touch()

    print(f"[Dashboard] Written to {html_dest}")
    print(f"[Dashboard] Data JSON: {json_path} ({json_path.stat().st_size // 1024}KB)")
    if portfolio_url:
        print(f"[Dashboard] Portfolio JSON: {portfolio_url}")
    return str(html_dest)


def _build_portfolio_json(lego_sets: list[dict], dashboard_data: dict) -> str:
    """
    Als PORTFOLIO_TOKEN is gezet: bouw portfolio_data.json op een token-gebaseerde URL.
    Geeft de relatieve URL terug (''), of lege string als token ontbreekt.
    """
    token = os.environ.get("PORTFOLIO_TOKEN", "").strip()
    if not token:
        return ""

    from src import db as _db
    positions = _db.get_portfolio_positions()
    # Geen early return bij lege positions — de sectie moet altijd zichtbaar zijn
    # zodat de gebruiker op "+ Positie" kan klikken voor de eerste positie.

    # Bouw lookup: set_number → huidige p50 per conditie
    p50_lookup: dict[str, dict[str, Optional[float]]] = {}
    for s in dashboard_data.get("sets", []):
        sn = s["set_number"]
        p50_lookup[sn] = {}
        for cond in ("NIB", "CIB"):
            vals = [
                pd.get(cond, {}).get("p50")
                for pd in s.get("platforms", {}).values()
                if pd.get(cond, {}).get("p50") is not None
            ]
            p50_lookup[sn][cond] = round(sum(vals) / len(vals), 2) if vals else None

    # Verrijk posities met huidige marktwaarde
    from datetime import timedelta
    set_names = {s["set_number"]: s["name"] for s in dashboard_data.get("sets", [])}
    enriched = []
    total_invested = 0.0
    total_market = 0.0
    realized_pnl = 0.0
    cutoff_12m = (datetime.now() - timedelta(days=365)).date().isoformat()
    unrealized_pnl_12m = 0.0
    invested_12m = 0.0

    for pos in positions:
        sn = pos["set_number"]
        cond = pos["condition"]
        qty = pos["quantity"]
        buy_price = pos["purchase_price"]
        invested = round(buy_price * qty, 2)
        total_invested += invested

        current_p50 = p50_lookup.get(sn, {}).get(cond)
        if pos["sold_price"] is not None:
            # Gesloten positie
            pnl = round((pos["sold_price"] - buy_price) * qty, 2)
            realized_pnl += pnl
            enriched.append({**pos, "set_name": set_names.get(sn, sn),
                              "current_p50": None, "unrealized_pnl": None,
                              "unrealized_pnl_pct": None, "invested": invested,
                              "realized_pnl": pnl})
        else:
            # Open positie
            if current_p50 is not None:
                market_val = round(current_p50 * qty, 2)
                total_market += market_val
                upnl = round(market_val - invested, 2)
                upnl_pct = round((current_p50 / buy_price - 1) * 100, 1) if buy_price else None
                # 12-maands ongerealiseerd: posities gekocht in de afgelopen 12 maanden
                if pos.get("purchase_date", "") >= cutoff_12m:
                    unrealized_pnl_12m += upnl
                    invested_12m += invested
            else:
                market_val = None
                upnl = None
                upnl_pct = None
            enriched.append({**pos, "set_name": set_names.get(sn, sn),
                              "current_p50": current_p50, "market_value": market_val,
                              "unrealized_pnl": upnl, "unrealized_pnl_pct": upnl_pct,
                              "invested": invested})

    portfolio_data = {
        "generated_at": datetime.now().isoformat(),
        "positions": enriched,
        "summary": {
            "total_invested": round(total_invested, 2),
            "total_market_value": round(total_market, 2),
            "unrealized_pnl": round(total_market - total_invested, 2),
            "unrealized_pnl_pct": round(
                (total_market / total_invested - 1) * 100, 1
            ) if total_invested else 0,
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl_12m": round(unrealized_pnl_12m, 2),
            "unrealized_pnl_12m_pct": round(
                (unrealized_pnl_12m / invested_12m) * 100, 1
            ) if invested_12m else 0,
        },
    }

    pf_path = DATA_OUTPUT_DIR / f"pf_{token}.json"
    pf_path.write_text(json.dumps(portfolio_data, ensure_ascii=False, indent=2))
    return f"./data/pf_{token}.json"
