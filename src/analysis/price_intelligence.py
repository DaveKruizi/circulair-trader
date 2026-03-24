"""
Price intelligence module.

Calculates realistic sell prices per set, per platform, per condition.

Methods:
- sell_price_fast      : p20 of active non-stale listings
                         → "what sells within ~7 days at this price"
- sell_price_realistic : time-weighted avg of recently disappeared listings (<21d listed)
                         → "likely transaction price (sold proxy)"

Also computes:
- p10/p25/p50 for context
- price_buckets: distribution in €10 steps for histogram
- disappeared_7d: sell velocity signal
"""

from datetime import datetime
from typing import Optional

BUCKET_SIZE = 10  # €10 buckets
STALE_DAYS = 21


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    sorted_v = sorted(values)
    idx = (pct / 100) * (len(sorted_v) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_v) - 1)
    return round(sorted_v[lo] + (idx - lo) * (sorted_v[hi] - sorted_v[lo]), 2)


def _price_bucket_key(price: float) -> str:
    low = int(price // BUCKET_SIZE) * BUCKET_SIZE
    return f"{low}-{low + BUCKET_SIZE}"


def compute_price_intelligence(
    set_number: str,
    platform: str,
    condition: str,
    retail_price: Optional[float] = None,
) -> dict:
    """
    Compute and persist price intelligence for one set/platform/condition combo.
    Saves result to price_snapshots table in SQLite.
    Returns the computed data dict.
    """
    from src import db

    today = datetime.now().date().isoformat()

    active = db.get_active_listings(set_number, platform, condition)

    # sell_price_fast uses only non-stale active listings
    all_active_prices = [r["price"] for r in active]
    fast_prices = []
    for r in active:
        first_seen = r.get("first_seen") or today
        try:
            days_old = (
                datetime.fromisoformat(today) - datetime.fromisoformat(first_seen)
            ).days
        except Exception:
            days_old = 0
        if days_old < STALE_DAYS:
            fast_prices.append(r["price"])

    # Use all active prices as fallback if not enough non-stale
    price_pool = fast_prices if len(fast_prices) >= 3 else all_active_prices

    sell_price_fast = _percentile(price_pool, 20)
    p10 = _percentile(all_active_prices, 10)
    p25 = _percentile(all_active_prices, 25)
    p50 = _percentile(all_active_prices, 50)

    # sell_price_realistic: median of disappeared listings <21d
    # (mediaan is eerlijker dan time-weighted avg — verdwenen ≠ verkocht,
    #  en korte listings zijn niet per se echte verkopen)
    # Filter: verdwenen listings met prijs > mediaan vraagprijs tellen niet mee —
    # die zijn waarschijnlijk niet echt verkocht maar bijv. teruggetrokken.
    disappeared = db.get_disappeared_listings(set_number, platform, condition, max_days=21)
    sell_price_realistic = None
    if disappeared:
        valid = [d for d in disappeared if p50 is None or d["price"] <= p50]
        if valid:
            sell_price_realistic = _percentile(sorted(d["price"] for d in valid), 50)

    # Price distribution in €10 buckets
    buckets: dict[str, int] = {}
    for p in all_active_prices:
        b = _price_bucket_key(p)
        buckets[b] = buckets.get(b, 0) + 1

    # Sell velocity: listings that disappeared in last 7 days
    disappeared_7d = db.get_disappeared_listings(set_number, platform, condition, max_days=7)

    db.save_price_snapshot(
        snapshot_date=today,
        set_number=set_number,
        platform=platform,
        condition_category=condition,
        active_count=len(active),
        disappeared_7d=len(disappeared_7d),
        p10=p10,
        p20=sell_price_fast,
        p25=p25,
        p50=p50,
        sell_price_fast=sell_price_fast,
        sell_price_realistic=sell_price_realistic,
    )

    return {
        "active_count": len(active),
        "sell_price_fast": sell_price_fast,
        "sell_price_realistic": sell_price_realistic,
        "p10": p10,
        "p25": p25,
        "p50": p50,
        "price_buckets": buckets,
        "disappeared_7d": len(disappeared_7d),
    }


def compute_all_sets(
    lego_sets: list[dict],
    platforms: list[str],
) -> dict[str, dict[str, dict[str, dict]]]:
    """
    Compute price intelligence for all sets, platforms, conditions (NIB + CIB).
    Returns nested dict: set_number -> platform -> condition -> intel_data
    """
    from src import db as db_module
    db_module.init_db()

    result: dict[str, dict[str, dict[str, dict]]] = {}
    for lego_set in lego_sets:
        set_number = lego_set["set_number"]
        retail = lego_set.get("retail_price")
        result[set_number] = {}
        for platform in platforms:
            result[set_number][platform] = {}
            for condition in ["NIB", "CIB"]:
                intel = compute_price_intelligence(set_number, platform, condition, retail)
                result[set_number][platform][condition] = intel
    return result


def get_price_history_for_dashboard(
    set_number: str,
    platforms: list[str],
) -> list[dict]:
    """
    Return time-series data for chart rendering.
    Format: [{date, platform, condition, sell_price_fast, sell_price_realistic, active_count}]
    """
    from src import db

    rows = []
    for platform in platforms:
        for condition in ["NIB", "CIB"]:
            history = db.get_price_history(set_number, platform, condition, limit=90)
            for h in history:
                rows.append({
                    "date": h["snapshot_date"],
                    "platform": platform,
                    "condition": condition,
                    "sell_price_fast": h["sell_price_fast"],
                    "sell_price_realistic": h["sell_price_realistic"],
                    "active_count": h["active_count"],
                })
    return sorted(rows, key=lambda r: r["date"])
