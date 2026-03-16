"""
Marktplaats.nl scraper.

Uses the `marktplaats` PyPI package (v0.4.0, updated Aug 2025).
Searches for items matching Vinted trend categories at low prices.
"""

import time
from dataclasses import dataclass
from typing import Optional

try:
    from marktplaats import Marktplaats
except ImportError:
    Marktplaats = None


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
    # How many days ago it was posted (rough estimate from date)
    days_listed: Optional[int] = None
    source: str = "marktplaats"


def _parse_listing(raw) -> Optional[MarktplaatsListing]:
    """Parse raw Marktplaats result into a MarktplaatsListing."""
    try:
        # The marktplaats package returns objects with varying attributes
        price = 0.0
        price_type = "unknown"

        price_info = getattr(raw, "price_info", None)
        if price_info:
            price = float(getattr(price_info, "price_cents", 0) or 0) / 100
            price_type = str(getattr(price_info, "price_type", "") or "")

        if price <= 0 and price_type not in ("free", "bidding"):
            return None

        images = getattr(raw, "images", []) or []
        image_url = ""
        if images:
            img = images[0]
            image_url = str(getattr(img, "medium_url", "") or "")

        seller = getattr(raw, "seller_information", None)
        seller_name = str(getattr(seller, "seller_name", "") or "") if seller else ""

        location = getattr(raw, "location", None)
        location_str = ""
        if location:
            city = getattr(location, "city_name", "") or ""
            country = getattr(location, "country_code", "") or ""
            location_str = f"{city}, {country}".strip(", ")

        return MarktplaatsListing(
            id=str(getattr(raw, "item_id", "") or ""),
            title=str(getattr(raw, "title", "") or ""),
            price=price,
            price_type=price_type,
            description=str(getattr(raw, "description", "") or "")[:500],
            category=str(getattr(raw, "category_name", "") or ""),
            location=location_str,
            url=f"https://www.marktplaats.nl/v/{getattr(raw, 'item_id', '')}",
            image_url=image_url,
            date_posted=str(getattr(raw, "date", "") or ""),
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
    if Marktplaats is None:
        print("[Marktplaats] Package not installed. Run: pip install marktplaats")
        return []

    results: list[MarktplaatsListing] = []
    seen_ids: set[str] = set()

    mp = Marktplaats()

    for term in search_terms:
        try:
            # The marktplaats package accepts search parameters
            listings = mp.search(
                query=term,
                limit=max_per_term,
            )
            for raw in listings or []:
                listing = _parse_listing(raw)
                if not listing:
                    continue
                if listing.id in seen_ids:
                    continue
                # Filter by max price (skip free/bidding for now)
                if listing.price_type == "fixed" and listing.price > max_price:
                    continue
                seen_ids.add(listing.id)
                results.append(listing)

            time.sleep(1.0)
        except Exception as e:
            print(f"[Marktplaats] Error scraping '{term}': {e}")
            continue

    return results
