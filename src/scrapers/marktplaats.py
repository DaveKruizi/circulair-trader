"""
Marktplaats.nl scraper.

Uses the `marktplaats` PyPI package.
Searches for items matching Vinted trend categories at low prices.
"""

import time
from dataclasses import dataclass
from typing import Optional

try:
    from marktplaats import SearchQuery, PriceType
    _MARKTPLAATS_AVAILABLE = True
except ImportError:
    _MARKTPLAATS_AVAILABLE = False


@dataclass
class MarktplaatsListing:
    id: str
    title: str
    price: float
    price_type: str  # "fixed", "bidding", "see_description", "free"
    description: str
    category: str
    location: str
    url: str
    image_url: str
    date_posted: str
    seller_name: str
    days_listed: Optional[int] = None
    source: str = "marktplaats"


def _parse_listing(raw) -> Optional[MarktplaatsListing]:
    """Parse a marktplaats Listing object into a MarktplaatsListing."""
    try:
        price = float(raw.price or 0)
        price_type_raw = str(raw.price_type.value if hasattr(raw.price_type, 'value') else raw.price_type)

        # Map price types
        if "FIXED" in price_type_raw.upper() or "FREE_TO_NEGOTIATE" in price_type_raw.upper():
            price_type = "fixed"
        elif "BID" in price_type_raw.upper() or "AUCTION" in price_type_raw.upper():
            price_type = "bidding"
        elif "FREE" in price_type_raw.upper():
            price_type = "free"
        else:
            price_type = "fixed"

        # Image
        image_url = ""
        if raw.first_image:
            image_url = str(getattr(raw.first_image, 'medium_url', '') or
                           getattr(raw.first_image, 'url', '') or '')

        # Seller
        seller_name = ""
        if raw.seller:
            seller_name = str(getattr(raw.seller, 'name', '') or '')

        # Location
        location_str = ""
        if raw.location:
            city = getattr(raw.location, 'city_name', '') or ''
            location_str = str(city)

        # Date
        date_str = str(raw.date) if raw.date else ""

        return MarktplaatsListing(
            id=str(raw.id),
            title=str(raw.title or ""),
            price=price,
            price_type=price_type,
            description=str(raw.description or "")[:500],
            category=str(getattr(raw, 'category_id', '') or ""),
            location=location_str,
            url=str(raw.link or f"https://www.marktplaats.nl/v/{raw.id}"),
            image_url=image_url,
            date_posted=date_str,
            seller_name=seller_name,
        )
    except Exception:
        return None


def scrape_marktplaats(
    search_terms: list[str],
    max_price: float = 50.0,
    max_per_term: int = 20,
) -> list[MarktplaatsListing]:
    """
    Search Marktplaats for items matching given terms under max_price.

    Args:
        search_terms: List of search terms to query.
        max_price: Maximum price filter in euros.
        max_per_term: Max results per search term.

    Returns:
        List of MarktplaatsListing objects.
    """
    if not _MARKTPLAATS_AVAILABLE:
        print("[Marktplaats] Package not installed. Run: pip install marktplaats")
        return []

    results: list[MarktplaatsListing] = []
    seen_ids: set[str] = set()

    for term in search_terms:
        try:
            search = SearchQuery(
                query=term,
                price_to=int(max_price * 100),  # price_to is in cents
                limit=max_per_term,
            )
            listings = search.get_listings()

            for raw in listings or []:
                listing = _parse_listing(raw)
                if not listing:
                    continue
                if listing.id in seen_ids:
                    continue
                if listing.price_type == "fixed" and listing.price > max_price:
                    continue
                seen_ids.add(listing.id)
                results.append(listing)

            time.sleep(1.0)
        except Exception as e:
            print(f"[Marktplaats] Error scraping '{term}': {e}")
            continue

    return results
