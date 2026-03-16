"""
Margin calculator for Circulair Trader.

Calculates net profit per item given:
- Buy price
- Estimated sell price (from Vinted trend data)
- Shipping cost
- Vinted Pro commission (placeholder — update when known)
- Monthly Vinted Pro subscription (amortized per sale)

NOTE: VINTED_COMMISSION_PCT is a placeholder (5%).
Update this once you have your actual Vinted Pro rate.
"""

from dataclasses import dataclass
from src.config import VINTED_COMMISSION_PCT, SHIPPING_COST, MIN_SELL_PRICE, MIN_NET_MARGIN


@dataclass
class MarginResult:
    buy_price: float
    estimated_sell_price: float
    shipping_cost: float
    vinted_commission: float
    vinted_commission_pct: float
    # Amortized Vinted Pro subscription per sale (€15/month ÷ estimated monthly sales)
    subscription_per_sale: float
    net_profit: float
    margin_pct: float
    is_viable: bool
    reason: str  # Why viable or not


def calculate_margin(
    buy_price: float,
    estimated_sell_price: float,
    shipping_cost: float = None,
    monthly_sales_estimate: int = 20,
) -> MarginResult:
    """
    Calculate net profit for a buy/sell opportunity.

    Args:
        buy_price: What you pay to acquire the item (euros).
        estimated_sell_price: Expected sell price on Vinted (euros).
        shipping_cost: Shipping to buyer. Defaults to config value.
        monthly_sales_estimate: Estimated monthly sales (for subscription amortization).

    Returns:
        MarginResult with full breakdown.
    """
    if shipping_cost is None:
        shipping_cost = SHIPPING_COST

    vinted_commission = estimated_sell_price * (VINTED_COMMISSION_PCT / 100)

    # Vinted Pro subscription ~€15/month, amortized over monthly sales
    vinted_pro_monthly = 15.0
    subscription_per_sale = vinted_pro_monthly / max(monthly_sales_estimate, 1)

    net_profit = (
        estimated_sell_price
        - buy_price
        - shipping_cost
        - vinted_commission
        - subscription_per_sale
    )

    margin_pct = (net_profit / estimated_sell_price * 100) if estimated_sell_price > 0 else 0

    # Viability checks
    if estimated_sell_price < MIN_SELL_PRICE:
        viable = False
        reason = f"Verkoopprijs €{estimated_sell_price:.2f} onder minimum van €{MIN_SELL_PRICE:.2f}"
    elif net_profit < MIN_NET_MARGIN:
        viable = False
        reason = f"Netto winst €{net_profit:.2f} onder minimum van €{MIN_NET_MARGIN:.2f}"
    elif buy_price <= 0:
        viable = False
        reason = "Inkoopprijs ontbreekt"
    else:
        viable = True
        reason = f"Netto winst €{net_profit:.2f} ({margin_pct:.0f}% marge)"

    return MarginResult(
        buy_price=round(buy_price, 2),
        estimated_sell_price=round(estimated_sell_price, 2),
        shipping_cost=round(shipping_cost, 2),
        vinted_commission=round(vinted_commission, 2),
        vinted_commission_pct=VINTED_COMMISSION_PCT,
        subscription_per_sale=round(subscription_per_sale, 2),
        net_profit=round(net_profit, 2),
        margin_pct=round(margin_pct, 1),
        is_viable=viable,
        reason=reason,
    )


def _median(values: list[float]) -> float:
    """Return the median of a non-empty list of floats."""
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 == 1 else (s[mid - 1] + s[mid]) / 2


def estimate_sell_price_from_trends(
    item_title: str,
    vinted_trends: list,
    fallback_multiplier: float = 2.5,
    buy_price: float = 0,
) -> float:
    """
    Estimate Vinted sell price based on trend data.

    Matching strategy:
    1. Find best trend via keyword overlap (most specific match wins).
    2. Use median price of sample_listings (high-favorite items) filtered to a
       realistic price range relative to the buy price (1.5x – 5x).
    3. Weight the result by the trend's demand_score (low demand → conservative).
    4. Falls back to avg_price if no usable samples, then buy_price * multiplier.

    Args:
        item_title: Title of the item to sell.
        vinted_trends: List of VintedTrend objects.
        fallback_multiplier: Multiplier on buy price if no trend match.
        buy_price: Buy price used for price-range filtering and fallback.

    Returns:
        Estimated sell price in euros.
    """
    title_lower = item_title.lower()
    title_words = set(title_lower.split())

    best_match = None
    best_score = 0.0

    for trend in vinted_trends:
        words = trend.search_term.lower().split()
        matched = sum(1 for w in words if w in title_words)
        if not matched:
            continue
        # Specificity: a full single-word match ("duplo") beats a partial
        # multi-word match ("kinderkleding pakket" with 1/2 words).
        score = matched * (matched / len(words))
        if score > best_score:
            best_score = score
            best_match = trend

    if best_match and best_score > 0:
        samples = getattr(best_match, "sample_listings", [])
        demand_score = getattr(best_match, "demand_score", 5.0)
        # Confidence factor: low demand → more conservative (0.70 – 1.00)
        confidence = 0.7 + (demand_score / 10) * 0.3

        # Filter samples to a realistic price bracket relative to buy price
        if buy_price > 0 and samples:
            relevant = [s for s in samples if buy_price * 1.5 <= s.price <= buy_price * 5]
        else:
            relevant = list(samples)

        if relevant:
            median_price = _median([s.price for s in relevant])
            return round(median_price * confidence, 2)

        # No relevant samples — fall back to avg_price with confidence weight
        return round(best_match.avg_price * confidence, 2)

    # No trend match — fall back to buy_price * multiplier
    if buy_price > 0:
        return round(buy_price * fallback_multiplier, 2)

    return 0.0
