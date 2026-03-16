"""
Marktplaats.nl scraper.

Uses the `marktplaats` PyPI package.
Focused on bulk/partij listings (quantity > 1) across all product categories.
"""

import concurrent.futures
import re
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
    quantity_available: int = 1
    days_listed: Optional[int] = None
    source: str = "marktplaats"


# Search terms for Marktplaats — mix van bulk/partij en losse winstgevende categorieën.
# Breder dan alleen "partij X": ook losse items die op Vinted goed verkopen.
SEARCH_TERMS = [
    # ── Bulk/partij ───────────────────────────────────────────────
    "partij kleding",
    "partij speelgoed",
    "partij schoenen",
    "partij boeken",
    "partij elektronica",
    "partij sportartikelen",
    "partij merkkleding",
    "partij vintage",
    "pallet kleding",
    "wholesale kleding",
    "partij te koop",
    "lot te koop",
    # ── Losse populaire categorieën ───────────────────────────────
    "lego",
    "playmobil",
    "kinderspeelgoed",
    "merkschoenen",
    "vintage kleding",
    "designer tas",
    "sportkleding",
    "sneakers",
    "kinderkleding",
    "babykleding",
    "elektronica",
    "telefoon",
]

# Legacy alias — used in mcp_server and other places that still reference BULK_SEARCH_TERMS
BULK_SEARCH_TERMS = SEARCH_TERMS

# Regex patterns to extract quantity from listing title + description
_QUANTITY_PATTERNS = [
    r'\b(\d+)\s*x\b',                  # "10x", "5 x"
    r'\b(\d+)\s*stuks?\b',             # "5 stuks", "3 stuk"
    r'\bpartij\s+van\s+(\d+)',          # "partij van 10"
    r'\blot\s+van\s+(\d+)',             # "lot van 5"
    r'\b(\d+)\s*exemplaren?\b',         # "3 exemplaren"
    r'\b(\d+)\s*items?\b',              # "10 items"
    r'\b(\d+)\s*st\.?\b',              # "5 st" / "5 st."
    r'\b(\d+)\s*paar\b',               # "3 paar" (shoes etc.)
    r'\b(\d+)\s*sets?\b',              # "4 sets"
    r'\b(\d+)\s*dozen\b',              # "2 dozen"
    r'\b(\d+)\s*pakken?\b',            # "6 pakken"
]

# Words that indicate a bulk listing even without a number
_BULK_INDICATOR_WORDS = {
    "partij", "lot", "bulk", "meerdere", "diverse", "assortiment",
    "voorraad", "wholesale", "collectie", "bundel", "pakket",
}


def _detect_quantity(title: str, description: str) -> int:
    """
    Detect quantity from listing title and description.

    Returns the detected quantity (≥1).  If no number found but bulk
    indicator words are present, returns 2 as a conservative estimate.
    """
    text = f"{title} {description}".lower()

    for pattern in _QUANTITY_PATTERNS:
        m = re.search(pattern, text)
        if m:
            try:
                qty = int(m.group(1))
                if qty > 1:
                    return qty
            except (IndexError, ValueError):
                continue

    # No explicit number — check for bulk vocabulary
    if any(word in text for word in _BULK_INDICATOR_WORDS):
        return 2

    return 1


def _parse_listing(raw) -> Optional[MarktplaatsListing]:
    """Parse a marktplaats Listing object into a MarktplaatsListing."""
    try:
        price = float(raw.price or 0)
        price_type_raw = str(raw.price_type.value if hasattr(raw.price_type, 'value') else raw.price_type)

        if "FIXED" in price_type_raw.upper() or "FREE_TO_NEGOTIATE" in price_type_raw.upper():
            price_type = "fixed"
        elif "BID" in price_type_raw.upper() or "AUCTION" in price_type_raw.upper():
            price_type = "bidding"
        elif "FREE" in price_type_raw.upper():
            price_type = "free"
        else:
            price_type = "fixed"

        image_url = ""
        if raw.first_image:
            image_url = str(getattr(raw.first_image, 'medium_url', '') or
                           getattr(raw.first_image, 'url', '') or '')

        seller_name = ""
        if raw.seller:
            seller_name = str(getattr(raw.seller, 'name', '') or '')

        location_str = ""
        if raw.location:
            city = getattr(raw.location, 'city_name', '') or ''
            location_str = str(city)

        date_str = str(raw.date) if raw.date else ""
        title = str(raw.title or "")
        description = str(raw.description or "")[:500]

        # Detect quantity from package-provided field first, then text
        raw_qty = getattr(raw, 'quantity', None) or getattr(raw, 'amount', None)
        if raw_qty and int(raw_qty) > 1:
            quantity = int(raw_qty)
        else:
            quantity = _detect_quantity(title, description)

        return MarktplaatsListing(
            id=str(raw.id),
            title=title,
            price=price,
            price_type=price_type,
            description=description,
            category=str(getattr(raw, 'category_id', '') or ""),
            location=location_str,
            url=str(raw.link or f"https://www.marktplaats.nl/v/{raw.id}"),
            image_url=image_url,
            date_posted=date_str,
            seller_name=seller_name,
            quantity_available=quantity,
        )
    except Exception:
        return None


def scrape_marktplaats(
    search_terms: list[str],
    max_price: float = 100.0,
    max_per_term: int = 20,
    min_quantity: int = 1,
) -> list[MarktplaatsListing]:
    """
    Search Marktplaats for items matching given terms.

    Args:
        search_terms:  List of search terms to query.
        max_price:     Maximum price filter in euros.
        max_per_term:  Max results per search term.
        min_quantity:  Only return listings with detected quantity >= this value.
                       Set to 2 to filter for bulk/partij listings only.

    Returns:
        List of MarktplaatsListing objects sorted by quantity descending.
    """
    if not _MARKTPLAATS_AVAILABLE:
        print("[Marktplaats] Package not installed. Run: pip install marktplaats")
        return []

    def _fetch_term(term: str) -> list[MarktplaatsListing]:
        try:
            search = SearchQuery(
                query=term,
                price_to=int(max_price * 100),  # price_to is in cents
                limit=max_per_term,
            )
            raw_listings = search.get_listings() or []
            time.sleep(1.0)  # per-worker rate limit
            return [
                lst for raw in raw_listings
                if (lst := _parse_listing(raw))
                and (lst.price_type != "fixed" or lst.price <= max_price)
                and lst.quantity_available >= min_quantity
            ]
        except Exception as e:
            print(f"[Marktplaats] Error scraping '{term}': {e}")
            return []

    seen_ids: set[str] = set()
    results: list[MarktplaatsListing] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for batch in pool.map(_fetch_term, search_terms):
            for listing in batch:
                if listing.id not in seen_ids:
                    seen_ids.add(listing.id)
                    results.append(listing)

    # Biggest lots first
    results.sort(key=lambda l: l.quantity_available, reverse=True)
    return results
