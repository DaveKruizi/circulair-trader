"""
Risk scorer for buy/sell opportunities.

Scores each opportunity on a 0-10 scale (10 = best).
Factors:
- Vinted demand score for the category (high demand = lower risk)
- Listing age on buying platform (old listing = lower demand there too)
- Price vs. average (very cheap may mean broken/incomplete)
- Whether cleaning/repair is mentioned (extra time cost)
- Fragility/size signals (should be filtered out but double-check)
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskScore:
    total_score: float          # 0-10, higher is better
    demand_score: float         # Vinted demand signal
    freshness_score: float      # How recent is the listing
    price_sanity_score: float   # Is price reasonable vs. avg
    condition_score: float      # Condition/effort required
    label: str                  # "Laag risico", "Gemiddeld", "Hoog risico"
    flags: list[str]            # Specific warnings


# Keywords that lower condition score (require cleaning/repair effort)
EFFORT_KEYWORDS = [
    "beschadigd", "kapot", "defect", "stuk", "schade", "krassen",
    "vlekken", "vlek", "reparatie", "mankement", "gebruikt",
    "damaged", "broken", "repair", "scratch", "stain",
]

# Keywords signaling fragility or large size (reduce score)
FRAGILITY_KEYWORDS = [
    "glas", "porselein", "spiegel", "kristal", "breekbaar",
    "groot", "zwaar", "pallet", "meubel", "bank", "tafel", "kast",
    "glass", "mirror", "fragile", "large", "heavy",
]


def score_opportunity(
    title: str,
    description: str = "",
    buy_price: float = 0,
    avg_buy_price: float = 0,
    days_listed: Optional[int] = None,
    vinted_demand_score: float = 5.0,
    margin_result=None,
) -> RiskScore:
    """
    Score a buy/sell opportunity.

    Args:
        title: Item title.
        description: Item description.
        buy_price: The price you'd pay.
        avg_buy_price: Average price for similar items (0 = unknown).
        days_listed: How many days the item has been listed (None = unknown).
        vinted_demand_score: Vinted demand score for this category (0-10).
        margin_result: MarginResult object (optional, used for sanity checks).

    Returns:
        RiskScore with breakdown.
    """
    flags: list[str] = []
    text = (title + " " + description).lower()

    # 1. Demand score (direct from Vinted trends, 0-10)
    demand = min(10.0, max(0.0, vinted_demand_score))

    # 2. Freshness score (how recently was it listed)
    freshness = 7.0  # Default neutral when unknown
    if days_listed is not None:
        if days_listed <= 1:
            freshness = 9.0
        elif days_listed <= 7:
            freshness = 8.0
        elif days_listed <= 14:
            freshness = 6.0
        elif days_listed <= 30:
            freshness = 4.0
        else:
            freshness = 2.0
            flags.append(f"Al {days_listed} dagen te koop — mogelijk moeilijk verkoopbaar")

    # 3. Price sanity (is buy price suspiciously low or high?)
    price_sanity = 7.0  # Neutral default
    if avg_buy_price > 0 and buy_price > 0:
        ratio = buy_price / avg_buy_price
        if ratio < 0.3:
            price_sanity = 4.0
            flags.append("Prijs erg laag vs. gemiddelde — controleer kwaliteit")
        elif ratio < 0.6:
            price_sanity = 8.0  # Good deal
        elif ratio < 1.0:
            price_sanity = 7.0
        elif ratio < 1.5:
            price_sanity = 5.0
            flags.append("Prijs aan de hoge kant")
        else:
            price_sanity = 3.0
            flags.append("Prijs veel hoger dan gemiddelde")

    # 4. Condition score (based on keywords in title/description)
    condition = 8.0  # Start optimistic
    effort_count = sum(1 for kw in EFFORT_KEYWORDS if kw in text)
    fragility_count = sum(1 for kw in FRAGILITY_KEYWORDS if kw in text)

    if effort_count >= 3:
        condition = 4.0
        flags.append("Meerdere signalen van schade/benodigde reiniging")
    elif effort_count >= 1:
        condition = 6.0
        flags.append("Mogelijk schoonmaak of kleine reparatie nodig")

    if fragility_count >= 2:
        condition = min(condition, 4.0)
        flags.append("Mogelijk groot of breekbaar — controleer verpakking")

    # Weighted average
    total = (
        demand * 0.35
        + freshness * 0.25
        + price_sanity * 0.20
        + condition * 0.20
    )
    total = round(min(10.0, max(0.0, total)), 1)

    if total >= 7.5:
        label = "Laag risico ✓"
    elif total >= 5.0:
        label = "Gemiddeld risico"
    else:
        label = "Hoog risico ✗"

    return RiskScore(
        total_score=total,
        demand_score=round(demand, 1),
        freshness_score=round(freshness, 1),
        price_sanity_score=round(price_sanity, 1),
        condition_score=round(condition, 1),
        label=label,
        flags=flags,
    )
