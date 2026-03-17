"""
Vinted price analyzer.

Loads vinted_prices.json and provides helpers for:
- Getting the realistic sell price per set + condition
- Velocity trend (is the set selling fast or slow on Vinted?)
- Price history data for charting
"""

import json
from pathlib import Path
from typing import Optional

VINTED_PRICES_PATH = Path("data/vinted_prices.json")
VINTED_HISTORY_PATH = Path("data/vinted_price_history.json")


def load_prices() -> dict:
    """Load current Vinted price data."""
    if VINTED_PRICES_PATH.exists():
        try:
            return json.loads(VINTED_PRICES_PATH.read_text())
        except Exception:
            return {}
    return {}


def load_history() -> dict:
    """Load Vinted price history."""
    if VINTED_HISTORY_PATH.exists():
        try:
            return json.loads(VINTED_HISTORY_PATH.read_text())
        except Exception:
            return {}
    return {}


def get_set_price_data(set_number: str, prices: Optional[dict] = None) -> Optional[dict]:
    """
    Get all price data for a single set.
    Returns dict of {condition_category: price_data_dict} or None.
    """
    if prices is None:
        prices = load_prices()
    sets_data = prices.get("sets", {})
    return sets_data.get(set_number)


def get_realistic_sell_price(
    set_number: str,
    condition_category: str,
    prices: Optional[dict] = None,
) -> Optional[float]:
    """
    Get the realistic sell price for a set + condition.
    Returns None if no data available.
    """
    set_data = get_set_price_data(set_number, prices)
    if not set_data:
        return None
    cat_data = set_data.get(condition_category, {})
    return cat_data.get("realistic_sell_price")


def get_vinted_listing_count(set_number: str, prices: Optional[dict] = None) -> int:
    """Get total Vinted listing count for a set (all conditions combined)."""
    set_data = get_set_price_data(set_number, prices)
    if not set_data:
        return 0
    all_data = set_data.get("all", {})
    return int(all_data.get("listing_count", 0))


def get_velocity_trend(set_number: str, history: Optional[dict] = None) -> str:
    """
    Determine velocity trend for a set based on listing count changes.

    Returns: "SNEL" (fast selling), "NORMAAL", "LANGZAAM" (slow selling), "ONBEKEND"
    """
    if history is None:
        history = load_history()

    set_history = history.get(set_number, {})
    if not set_history:
        return "ONBEKEND"

    weeks = sorted(set_history.keys())
    if len(weeks) < 2:
        return "ONBEKEND"

    # Compare last 2 weeks listing count
    last_week = set_history[weeks[-1]]
    prev_week = set_history[weeks[-2]]

    last_count = last_week.get("all", {}).get("listing_count", 0)
    prev_count = prev_week.get("all", {}).get("listing_count", 0)

    if prev_count == 0:
        return "ONBEKEND"

    change_pct = (last_count - prev_count) / prev_count

    if change_pct < -0.15:    # >15% drop in listings = selling fast
        return "SNEL"
    elif change_pct > 0.15:   # >15% increase = slow selling / more supply
        return "LANGZAAM"
    else:
        return "NORMAAL"


def get_chart_data(set_number: str, history: Optional[dict] = None) -> list[dict]:
    """
    Get chart-ready data for a set's price history.

    Returns list of:
    {week: "2026-W10", NIB: 185.0, CIB: 140.0, incomplete: 85.0, all: 160.0}
    Sorted oldest to newest.
    """
    if history is None:
        history = load_history()

    set_history = history.get(set_number, {})
    if not set_history:
        return []

    chart = []
    for week in sorted(set_history.keys()):
        week_data = set_history[week]
        point: dict = {"week": week}
        for cat in ["NIB", "CIB", "incomplete", "all"]:
            cat_data = week_data.get(cat, {})
            price = cat_data.get("realistic_sell_price")
            if price:
                point[cat] = price
        chart.append(point)

    return chart


def enrich_set_summary(lego_set: dict, prices: Optional[dict] = None, history: Optional[dict] = None) -> dict:
    """
    Add Vinted price info and velocity to a lego_set dict.
    Returns a new dict with added fields.
    """
    set_number = lego_set["set_number"]
    enriched = dict(lego_set)

    set_price_data = get_set_price_data(set_number, prices)
    enriched["vinted_prices"] = set_price_data or {}
    enriched["vinted_total_count"] = get_vinted_listing_count(set_number, prices)
    enriched["velocity_trend"] = get_velocity_trend(set_number, history)
    enriched["price_chart_data"] = get_chart_data(set_number, history)

    return enriched
