"""
Vinted scraper — trend analysis via public listings.

Uses the vinted-scraper PyPI package which wraps Vinted's internal API.
Collects active listings to derive:
- Which categories/products appear frequently
- Average asking prices per category
- Listing age (proxy for demand: old = low demand)
- Favorites count (proxy for interest)

Note: Vinted has no official public API. This uses the unofficial API
that the app itself uses. It may break if Vinted changes their API.
Use responsibly and respect rate limits.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from vinted_scraper import VintedScraper


@dataclass
class VintedListing:
    id: str
    title: str
    price: float
    currency: str
    brand: str
    category: str
    size: str
    condition: str
    favorites_count: int
    views_count: int
    created_at: str
    url: str
    photo_url: str
    # Derived field: estimated days listed (approximate, based on listing ID gap)
    days_listed: Optional[int] = None


@dataclass
class VintedTrend:
    category: str
    search_term: str
    avg_price: float
    min_price: float
    max_price: float
    listing_count: int
    avg_favorites: float
    # Listings with high favorites relative to listing age = high demand signal
    demand_score: float
    sample_listings: list[VintedListing] = field(default_factory=list)


# Categories and search terms to monitor for resale potential.
# Focus on small, non-fragile items with good margin potential.
SEARCH_TARGETS = [
    # Fashion & accessories (small, light, good margins)
    {"term": "vintage sieraden", "category": "Sieraden"},
    {"term": "designer tas", "category": "Tassen"},
    {"term": "sneakers", "category": "Schoenen"},
    {"term": "vintage kleding", "category": "Kleding"},
    {"term": "zonnebril", "category": "Accessoires"},
    {"term": "horloge vintage", "category": "Horloges"},
    # Home & lifestyle (small items)
    {"term": "vintage servies", "category": "Wonen"},
    {"term": "vintage lamp", "category": "Wonen"},
    # Electronics (small)
    {"term": "vintage camera", "category": "Elektronica"},
    {"term": "koptelefoon", "category": "Elektronica"},
    # Collectibles
    {"term": "vintage speelgoed", "category": "Speelgoed"},
    {"term": "lego vintage", "category": "Speelgoed"},
]


def _parse_listing(item) -> Optional[VintedListing]:
    """Parse a raw Vinted item into a VintedListing."""
    try:
        price_raw = getattr(item, "price", None)
        price = float(price_raw) if price_raw else 0.0
        if price < 1:
            return None

        return VintedListing(
            id=str(getattr(item, "id", "")),
            title=str(getattr(item, "title", "")),
            price=price,
            currency=str(getattr(item, "currency", "EUR")),
            brand=str(getattr(item, "brand_title", "") or ""),
            category=str(getattr(item, "category_title", "") or ""),
            size=str(getattr(item, "size_title", "") or ""),
            condition=str(getattr(item, "status", "") or ""),
            favorites_count=int(getattr(item, "favourite_count", 0) or 0),
            views_count=int(getattr(item, "view_count", 0) or 0),
            created_at=str(getattr(item, "created_at_ts", "") or ""),
            url=str(getattr(item, "url", "") or ""),
            photo_url=(
                item.photos[0].url
                if getattr(item, "photos", None)
                else ""
            ),
        )
    except Exception:
        return None


def _compute_demand_score(listings: list[VintedListing]) -> float:
    """
    Score 0-10. Higher = more demand.
    Based on avg favorites and number of listings (more listings = more supply,
    which dilutes demand score).
    """
    if not listings:
        return 0.0
    avg_fav = sum(l.favorites_count for l in listings) / len(listings)
    # Many listings with high favorites = high demand
    # Few listings with high favorites = niche but high demand
    # Normalize: 5 avg favorites = score of 5, capped at 10
    score = min(10.0, avg_fav * 1.5)
    return round(score, 1)


def scrape_vinted_trends(
    domains: list[str] = None,
    max_per_term: int = 30,
    min_price: float = 5.0,
) -> list[VintedTrend]:
    """
    Scrape Vinted for trending products and price data.

    Args:
        domains: Vinted domains to scrape. Defaults to NL + international.
        max_per_term: Max listings to fetch per search term.
        min_price: Minimum price to include in analysis.

    Returns:
        List of VintedTrend objects sorted by demand_score desc.
    """
    if domains is None:
        domains = ["https://www.vinted.nl", "https://www.vinted.com"]

    trends: list[VintedTrend] = []

    for target in SEARCH_TARGETS:
        term = target["term"]
        category = target["category"]
        all_listings: list[VintedListing] = []

        for domain in domains:
            try:
                scraper = VintedScraper(domain)
                params = {
                    "search_text": term,
                    "price_from": min_price,
                    "per_page": max_per_term,
                    "order": "newest_first",
                }
                raw_items = scraper.search(params)
                for item in raw_items or []:
                    listing = _parse_listing(item)
                    if listing:
                        all_listings.append(listing)
                # Polite rate limiting
                time.sleep(1.5)
            except Exception as e:
                print(f"[Vinted] Error scraping '{term}' on {domain}: {e}")
                continue

        if not all_listings:
            continue

        prices = [l.price for l in all_listings]
        trend = VintedTrend(
            category=category,
            search_term=term,
            avg_price=round(sum(prices) / len(prices), 2),
            min_price=round(min(prices), 2),
            max_price=round(max(prices), 2),
            listing_count=len(all_listings),
            avg_favorites=round(
                sum(l.favorites_count for l in all_listings) / len(all_listings), 1
            ),
            demand_score=_compute_demand_score(all_listings),
            # Keep top 5 most-favorited as samples
            sample_listings=sorted(
                all_listings, key=lambda l: l.favorites_count, reverse=True
            )[:5],
        )
        trends.append(trend)

    return sorted(trends, key=lambda t: t.demand_score, reverse=True)
