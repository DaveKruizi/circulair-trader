"""
Margin calculator for LEGO deals.

Calculates expected profit per deal based on:
- Buy price (Marktplaats)
- Condition category (NIB / CIB / incomplete / unknown)
- Expected sell price on Vinted per condition (from vinted_prices.json)
- Vinted platform costs (commission + shipping)
"""

from dataclasses import dataclass
from typing import Optional

# Vinted platform costs
VINTED_COMMISSION_PCT = 0.08         # 8% seller commission (Pro seller rate estimate)
SHIPPING_COST = 5.50                 # average PostNL parcel shipping cost

# Condition-based price adjustment multipliers relative to NIB
CONDITION_MULTIPLIERS = {
    "NIB": 1.00,
    "CIB": 0.75,        # typically 25% less than NIB
    "incomplete": 0.45, # typically 45-55% less than NIB
    "unknown": 0.70,    # conservative estimate
}


@dataclass
class MarginResult:
    buy_price: float
    condition_category: str
    expected_sell_price: Optional[float]
    vinted_commission: Optional[float]
    shipping_cost: float
    net_profit: Optional[float]
    margin_pct: Optional[float]
    is_viable: bool
    sell_price_source: str  # "vinted_NIB", "vinted_CIB", etc., or "estimated" / "no_data"


def calculate_margin(
    buy_price: float,
    condition_category: str,
    vinted_price_data: Optional[dict],
) -> MarginResult:
    """
    Calculate the expected margin for a deal.

    Args:
        buy_price: purchase price on Marktplaats
        condition_category: "NIB", "CIB", "incomplete", or "unknown"
        vinted_price_data: dict from vinted_prices.json for this set
                           (key: condition_category -> SetPriceData dict)
                           May be None if no Vinted data available yet.

    Returns:
        MarginResult with full breakdown
    """
    sell_price, sell_source = _get_sell_price(condition_category, vinted_price_data)

    if sell_price is None or sell_price <= 0:
        return MarginResult(
            buy_price=buy_price,
            condition_category=condition_category,
            expected_sell_price=None,
            vinted_commission=None,
            shipping_cost=SHIPPING_COST,
            net_profit=None,
            margin_pct=None,
            is_viable=False,
            sell_price_source="no_data",
        )

    commission = round(sell_price * VINTED_COMMISSION_PCT, 2)
    total_costs = buy_price + commission + SHIPPING_COST
    net_profit = round(sell_price - total_costs, 2)
    margin_pct = round((net_profit / sell_price) * 100, 1) if sell_price > 0 else 0.0
    is_viable = net_profit > 0

    return MarginResult(
        buy_price=buy_price,
        condition_category=condition_category,
        expected_sell_price=round(sell_price, 2),
        vinted_commission=commission,
        shipping_cost=SHIPPING_COST,
        net_profit=net_profit,
        margin_pct=margin_pct,
        is_viable=is_viable,
        sell_price_source=sell_source,
    )


def _get_sell_price(
    condition_category: str,
    vinted_data: Optional[dict],
) -> tuple[Optional[float], str]:
    """
    Determine the expected sell price.
    1. Try exact condition category from Vinted data
    2. Try "all" category and apply condition multiplier
    3. Return None if no data
    """
    if not vinted_data:
        return None, "no_data"

    cat_data = vinted_data.get(condition_category, {})
    if cat_data and cat_data.get("realistic_sell_price"):
        return float(cat_data["realistic_sell_price"]), f"vinted_{condition_category}"

    all_data = vinted_data.get("all", {})
    if all_data and all_data.get("realistic_sell_price"):
        base = float(all_data["realistic_sell_price"])
        multiplier = CONDITION_MULTIPLIERS.get(condition_category, 0.70)
        adjusted = base * multiplier
        return round(adjusted, 2), "estimated_from_all"

    return None, "no_data"


def all_condition_margins(
    buy_price: float,
    vinted_price_data: Optional[dict],
) -> dict[str, MarginResult]:
    """
    Calculate margins for all condition categories at once.
    Useful for displaying all three scenarios in the dashboard.
    """
    return {
        cat: calculate_margin(buy_price, cat, vinted_price_data)
        for cat in ["NIB", "CIB", "incomplete", "unknown"]
    }
