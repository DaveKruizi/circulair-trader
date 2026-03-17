"""
Deal filter — applies the 3 deal criteria to determine if a listing qualifies.

Rules:
1. Fixed price <= 50% of reference price             → HALFPRIJS
2. Bidding + current bid <= 50% of reference price   → BIEDING_DEAL
3. Price > 50% reference BUT no bids AND >= 4 weeks  → OUD_AANBOD (negotiation potential)

Reference price:
  - Active set  → retail_price
  - Retired set → market_value_new (if set, otherwise retail_price)
"""

from dataclasses import dataclass
from typing import Optional

HALF_PRICE_THRESHOLD = 0.50   # 50% of reference price
OLD_LISTING_DAYS = 28         # 4 weeks
OLD_BID_THRESHOLD = 0.30      # old listings only shown if no bids OR bid < 30% reference


@dataclass
class DealVerdict:
    qualifies: bool
    deal_type: Optional[str]   # "HALFPRIJS", "BIEDING_DEAL", "OUD_AANBOD", None
    deal_badge: Optional[str]  # emoji + label for display
    reference_price: float
    discount_pct: Optional[float]  # how far below reference price (0-100)


def get_reference_price(lego_set: dict) -> float:
    """
    Returns the reference price for deal filtering.
    Uses market_value_new for retired sets if available.
    """
    if lego_set.get("is_retired") and lego_set.get("market_value_new"):
        return float(lego_set["market_value_new"])
    return float(lego_set["retail_price"])


def evaluate_deal(listing: dict, lego_set: dict) -> DealVerdict:
    """
    Evaluate whether a listing qualifies as a deal.

    Args:
        listing: dict with keys: price, price_type, current_bid, days_listed
        lego_set: dict from lego_sets.json with retail_price, market_value_new, is_retired

    Returns:
        DealVerdict with qualification status and deal type.
    """
    ref = get_reference_price(lego_set)
    price = float(listing.get("price") or 0)
    price_type = str(listing.get("price_type") or "fixed")
    current_bid = listing.get("current_bid")
    days_listed = int(listing.get("days_listed") or 0)
    ask_price = float(listing.get("ask_price") or price)

    threshold = ref * HALF_PRICE_THRESHOLD

    # Rule 1: Fixed price at or below 50% reference
    if price_type == "fixed" and price > 0 and price <= threshold:
        discount = round((1 - price / ref) * 100, 1)
        return DealVerdict(
            qualifies=True,
            deal_type="HALFPRIJS",
            deal_badge="🔥 Halfprijs",
            reference_price=ref,
            discount_pct=discount,
        )

    # Rule 2: Bidding + current bid at or below 50% reference
    if price_type == "bidding" and current_bid is not None and current_bid > 0:
        if current_bid <= threshold:
            discount = round((1 - current_bid / ref) * 100, 1)
            return DealVerdict(
                qualifies=True,
                deal_type="BIEDING_DEAL",
                deal_badge="⚡ Bieding deal",
                reference_price=ref,
                discount_pct=discount,
            )

    # Rule 3: Listed 4+ weeks with no meaningful bids
    no_bid = current_bid is None or current_bid == 0 or current_bid < ref * OLD_BID_THRESHOLD
    if days_listed >= OLD_LISTING_DAYS and no_bid:
        # Calculate discount based on ask price vs reference
        discount = round((1 - ask_price / ref) * 100, 1) if ask_price < ref else 0.0
        return DealVerdict(
            qualifies=True,
            deal_type="OUD_AANBOD",
            deal_badge="⌛ Oud aanbod",
            reference_price=ref,
            discount_pct=discount,
        )

    return DealVerdict(
        qualifies=False,
        deal_type=None,
        deal_badge=None,
        reference_price=ref,
        discount_pct=None,
    )


def is_new_today(listing: dict) -> bool:
    """Returns True if the listing was first seen today."""
    from datetime import datetime
    today = datetime.now().date().isoformat()
    return listing.get("first_seen", "") == today


def filter_deals(
    listings: list[dict],
    lego_set: dict,
) -> list[dict]:
    """
    Filter a list of listings to only qualifying deals.
    Adds 'deal_verdict' key to each qualifying listing.
    Returns filtered + annotated list, sorted by: new today first, then by deal_type.
    """
    qualified = []
    for listing in listings:
        verdict = evaluate_deal(listing, lego_set)
        if verdict.qualifies:
            annotated = {**listing}
            annotated["deal_verdict"] = {
                "deal_type": verdict.deal_type,
                "deal_badge": verdict.deal_badge,
                "reference_price": verdict.reference_price,
                "discount_pct": verdict.discount_pct,
            }
            annotated["is_new_today"] = is_new_today(listing)
            qualified.append(annotated)

    # Sort: new today first, then HALFPRIJS > BIEDING_DEAL > OUD_AANBOD, then by date
    type_order = {"HALFPRIJS": 0, "BIEDING_DEAL": 1, "OUD_AANBOD": 2}
    qualified.sort(
        key=lambda x: (
            0 if x.get("is_new_today") else 1,
            type_order.get(x["deal_verdict"]["deal_type"], 9),
            x.get("date_posted", ""),
        ),
        reverse=False,
    )
    # Reverse date within same type (newest first)
    qualified.sort(
        key=lambda x: x.get("date_posted", ""),
        reverse=True,
    )
    # Re-apply primary sort: new today and type order on top
    qualified.sort(
        key=lambda x: (
            0 if x.get("is_new_today") else 1,
            type_order.get(x["deal_verdict"]["deal_type"], 9),
        ),
    )
    return qualified
