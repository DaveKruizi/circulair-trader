"""
Marktplaats.nl LEGO scraper.

Per LEGO set: search by set number AND by product name.
For bidding listings: fetch the listing page to extract the current highest bid.
Tracks first-seen dates and price changes via seen_deals.json.
"""

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

try:
    from marktplaats import SearchQuery
    _MARKTPLAATS_AVAILABLE = True
except ImportError:
    _MARKTPLAATS_AVAILABLE = False


SEEN_DEALS_PATH = Path("data/seen_deals.json")
DEALS_DATA_PATH = Path("data/marktplaats_deals.json")


@dataclass
class LegoListing:
    id: str
    set_number: str
    title: str
    price: float
    price_type: str            # "fixed", "bidding", "free", "see_description"
    current_bid: Optional[float]
    ask_price: float           # original asking/starting price even when bidding
    condition_category: str    # "NIB", "CIB", "incomplete", "unknown"
    description: str
    location: str
    url: str
    image_url: str
    date_posted: str           # ISO date string
    days_listed: int
    seller_name: str
    first_seen: str            # ISO date when we first scraped this listing
    price_changed: bool = False
    previous_price: Optional[float] = None
    source: str = "marktplaats"


def _load_seen_deals() -> dict:
    if SEEN_DEALS_PATH.exists():
        try:
            return json.loads(SEEN_DEALS_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_seen_deals(seen: dict) -> None:
    SEEN_DEALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Prune entries older than 90 days
    cutoff = (datetime.now() - timedelta(days=90)).date().isoformat()
    pruned = {k: v for k, v in seen.items() if v.get("last_seen", "2000-01-01") >= cutoff}
    SEEN_DEALS_PATH.write_text(json.dumps(pruned, ensure_ascii=False, indent=2))


def _days_since(date_str: str) -> int:
    """Calculate days since a date string (ISO format or Dutch shorthand)."""
    if not date_str:
        return 0
    try:
        # Try ISO format first
        posted = datetime.fromisoformat(date_str.split("T")[0]).date()
        return (datetime.now().date() - posted).days
    except Exception:
        return 0


def _classify_condition(title: str, description: str) -> str:
    """
    Classify listing condition into one of 4 categories based on text.

    NIB  = Nieuw In Doos (sealed, unopened)
    CIB  = Compleet In Doos (opened but complete with box + manual)
    incomplete = missing box, manual, or pieces
    unknown = cannot determine
    """
    text = (title + " " + description).lower()

    # NIB keywords (check first — strongest signal)
    nib_keywords = [
        "sealed", "ongeopend", "new in box", "nib", "verzegeld",
        "nooit geopend", "nieuw in verpakking", "nieuw in doos",
        "factory sealed", "geseald", "origineel verzegeld",
    ]
    if any(kw in text for kw in nib_keywords):
        return "NIB"

    # Incomplete keywords (check before CIB — incomplete overrides)
    incomplete_keywords = [
        "zonder doos", "geen doos", "zonder handleiding", "geen handleiding",
        "losse steentjes", "los", "niet compleet", "incompleet",
        "onderdelen ontbreken", "mist", "beschadigd", "kapot",
        "zonder instructies", "geen instructies", "steentjes alleen",
        "doos beschadigd", "doos mist", "handleiding mist",
    ]
    if any(kw in text for kw in incomplete_keywords):
        return "incomplete"

    # CIB keywords
    cib_keywords = [
        "compleet", "met doos", "met handleiding", "inclusief handleiding",
        "originele doos", "volledig", "met instructies", "inclusief instructies",
        "doos aanwezig", "handleiding aanwezig", "complete set",
        "met alle onderdelen", "volledig compleet",
    ]
    if any(kw in text for kw in cib_keywords):
        return "CIB"

    return "unknown"


def _fetch_current_bid(url: str) -> Optional[float]:
    """
    Fetch the listing page and extract the current highest bid.
    Returns None if no bid found or on error.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "nl-NL,nl;q=0.9",
        }
        resp = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Pattern 1: "Hoogste bieding: €X" or "Huidige bieding: €X"
        text = soup.get_text(" ", strip=True)
        patterns = [
            r"[Hh]oogste\s+bieding[:\s]+[€EUR\s]*([0-9.,]+)",
            r"[Hh]uidige\s+bieding[:\s]+[€EUR\s]*([0-9.,]+)",
            r"[Bb]od[:\s]+[€EUR\s]*([0-9.,]+)",
            r"[Bb]ieding[:\s]+[€EUR\s]*([0-9.,]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                amount_str = m.group(1).replace(".", "").replace(",", ".")
                try:
                    return float(amount_str)
                except ValueError:
                    continue

        # Pattern 2: JSON-LD or meta bid data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict):
                    bid = data.get("highPrice") or data.get("currentBid")
                    if bid:
                        return float(bid)
            except Exception:
                pass

        return None
    except Exception:
        return None


def _parse_listing(raw, set_number: str, seen: dict, today: str) -> Optional[LegoListing]:
    """Convert a raw Marktplaats listing into a LegoListing."""
    try:
        listing_id = str(raw.id)
        title = str(raw.title or "")
        description = str(raw.description or "")[:600]
        price = float(raw.price or 0)

        price_type_raw = str(
            raw.price_type.value if hasattr(raw.price_type, "value") else raw.price_type
        ).upper()

        if "BID" in price_type_raw or "AUCTION" in price_type_raw:
            price_type = "bidding"
        elif "FREE" in price_type_raw and "NEGOTIATE" not in price_type_raw:
            price_type = "free"
        else:
            price_type = "fixed"

        image_url = ""
        if raw.first_image:
            image_url = str(
                getattr(raw.first_image, "medium_url", "")
                or getattr(raw.first_image, "url", "")
                or ""
            )

        seller_name = str(getattr(raw.seller, "name", "") or "") if raw.seller else ""

        location_str = ""
        if raw.location:
            city = getattr(raw.location, "city_name", "") or ""
            location_str = str(city)

        date_str = str(raw.date) if raw.date else ""
        days = _days_since(date_str)

        url = str(raw.link or f"https://www.marktplaats.nl/v/{listing_id}")
        condition = _classify_condition(title, description)

        # Track first-seen and price changes
        prev = seen.get(listing_id)
        first_seen = prev["first_seen"] if prev else today
        price_changed = bool(prev and prev.get("price") != price and prev.get("price") is not None)
        previous_price = prev.get("price") if price_changed else None

        # Update seen dict
        seen[listing_id] = {
            "first_seen": first_seen,
            "last_seen": today,
            "price": price,
            "title": title[:80],
            "set_number": set_number,
        }

        return LegoListing(
            id=listing_id,
            set_number=set_number,
            title=title,
            price=price,
            price_type=price_type,
            current_bid=None,  # fetched later for bidding listings
            ask_price=price,
            condition_category=condition,
            description=description,
            location=location_str,
            url=url,
            image_url=image_url,
            date_posted=date_str,
            days_listed=days,
            seller_name=seller_name,
            first_seen=first_seen,
            price_changed=price_changed,
            previous_price=previous_price,
        )
    except Exception as e:
        print(f"[Marktplaats] Parse error for listing: {e}")
        return None


def scrape_set(set_number: str, name: str, max_price: float = 9999.0) -> list[LegoListing]:
    """
    Scrape Marktplaats for a single LEGO set.
    Searches by set number AND by name (deduplicates results).
    Fetches current bid for bidding-type listings.
    """
    if not _MARKTPLAATS_AVAILABLE:
        print("[Marktplaats] Package not installed. Run: pip install marktplaats")
        return []

    seen = _load_seen_deals()
    today = datetime.now().date().isoformat()

    # Build search queries
    # Use name stripped to first 3 meaningful words to avoid over-specificity
    name_words = [w for w in name.split() if len(w) > 2][:3]
    name_query = " ".join(name_words)
    queries = list(dict.fromkeys([f"{set_number} lego", f"lego {name_query}"]))

    seen_ids: set[str] = set()
    results: list[LegoListing] = []

    for query in queries:
        try:
            search = SearchQuery(
                query=query,
                limit=30,
            )
            raw_listings = search.get_listings() or []
            time.sleep(1.2)  # rate limit
            for raw in raw_listings:
                lst = _parse_listing(raw, set_number, seen, today)
                if lst and lst.id not in seen_ids:
                    # Basic relevance check: title must contain set number OR major name word
                    title_lower = lst.title.lower()
                    name_lower = name.lower()
                    set_in_title = set_number in title_lower
                    name_in_title = any(
                        w.lower() in title_lower
                        for w in name.split()
                        if len(w) > 3
                    )
                    if set_in_title or name_in_title:
                        seen_ids.add(lst.id)
                        results.append(lst)
        except Exception as e:
            print(f"[Marktplaats] Error scraping '{query}': {e}")

    # Fetch current bids for bidding listings (sequential, max 10 per set)
    bidding = [r for r in results if r.price_type == "bidding"][:10]
    for lst in bidding:
        bid = _fetch_current_bid(lst.url)
        lst.current_bid = bid
        time.sleep(0.5)

    _save_seen_deals(seen)
    return results


def scrape_all_sets(lego_sets: list[dict]) -> dict[str, list[LegoListing]]:
    """
    Scrape all LEGO sets and return a dict of set_number -> list of listings.
    Also saves results to data/marktplaats_deals.json.
    """
    results: dict[str, list[LegoListing]] = {}

    for i, lego_set in enumerate(lego_sets, 1):
        set_number = lego_set["set_number"]
        name = lego_set["name"]
        print(f"[Marktplaats] [{i}/{len(lego_sets)}] Scraping set {set_number}: {name}")
        listings = scrape_set(set_number, name)
        results[set_number] = listings
        print(f"  → {len(listings)} listings found")
        time.sleep(0.5)  # extra gap between sets

    # Persist to disk
    _save_deals_data(results)
    return results


def _save_deals_data(results: dict[str, list[LegoListing]]) -> None:
    """Save scraped deals to data/marktplaats_deals.json."""
    DEALS_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        "scraped_at": datetime.now().isoformat(),
        "sets": {
            set_number: [
                {
                    "id": lst.id,
                    "set_number": lst.set_number,
                    "title": lst.title,
                    "price": lst.price,
                    "price_type": lst.price_type,
                    "current_bid": lst.current_bid,
                    "ask_price": lst.ask_price,
                    "condition_category": lst.condition_category,
                    "description": lst.description,
                    "location": lst.location,
                    "url": lst.url,
                    "image_url": lst.image_url,
                    "date_posted": lst.date_posted,
                    "days_listed": lst.days_listed,
                    "seller_name": lst.seller_name,
                    "first_seen": lst.first_seen,
                    "price_changed": lst.price_changed,
                    "previous_price": lst.previous_price,
                }
                for lst in listings
            ]
            for set_number, listings in results.items()
        },
    }
    DEALS_DATA_PATH.write_text(json.dumps(serializable, ensure_ascii=False, indent=2))


def load_deals_data() -> dict:
    """Load previously scraped deals from disk."""
    if DEALS_DATA_PATH.exists():
        try:
            return json.loads(DEALS_DATA_PATH.read_text())
        except Exception:
            return {}
    return {}
