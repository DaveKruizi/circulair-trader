"""
Marktplaats.nl LEGO scraper.

Per LEGO set: search by set number AND by product name.
For bidding listings: fetch the listing page to extract the current highest bid.
Tracks first-seen dates and price changes via seen_deals.json.
"""

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

try:
    from marktplaats import SearchQuery, PriceType
    _MARKTPLAATS_AVAILABLE = True
except ImportError:
    _MARKTPLAATS_AVAILABLE = False

SEEN_DEALS_PATH = Path("data/seen_deals.json")
DEALS_DATA_PATH = Path("data/marktplaats_deals.json")


def _load_seen_deals() -> dict:
    if SEEN_DEALS_PATH.exists():
        try:
            return json.loads(SEEN_DEALS_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_seen_deals(seen: dict) -> None:
    SEEN_DEALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    cutoff = (datetime.now() - timedelta(days=90)).date().isoformat()
    pruned = {k: v for k, v in seen.items() if v.get("last_seen", "2000-01-01") >= cutoff}
    SEEN_DEALS_PATH.write_text(json.dumps(pruned, ensure_ascii=False, indent=2))


def _days_since(dt: Optional[datetime]) -> int:
    """Calculate days since a datetime object."""
    if not dt:
        return 0
    try:
        return (datetime.now().date() - dt.date()).days
    except Exception:
        return 0


def _classify_condition(title: str, description: str) -> str:
    """
    Classify listing condition into one of 4 categories.
    NIB  = Nieuw In Doos (sealed, unopened)
    CIB  = Compleet In Doos (opened but complete with box + manual)
    incomplete = missing box, manual, or pieces
    unknown = cannot determine
    """
    text = (title + " " + description).lower()

    nib_keywords = [
        "sealed", "ongeopend", "new in box", "nib", "verzegeld",
        "nooit geopend", "nieuw in verpakking", "nieuw in doos",
        "factory sealed", "geseald", "origineel verzegeld",
    ]
    if any(kw in text for kw in nib_keywords):
        return "NIB"

    incomplete_keywords = [
        "zonder doos", "geen doos", "zonder handleiding", "geen handleiding",
        "losse steentjes", "los", "niet compleet", "incompleet",
        "onderdelen ontbreken", "beschadigd", "kapot",
        "zonder instructies", "geen instructies", "steentjes alleen",
        "doos beschadigd", "doos mist", "handleiding mist",
    ]
    if any(kw in text for kw in incomplete_keywords):
        return "incomplete"

    cib_keywords = [
        "compleet", "met doos", "met handleiding", "inclusief handleiding",
        "originele doos", "volledig", "met instructies", "inclusief instructies",
        "doos aanwezig", "handleiding aanwezig", "complete set",
        "met alle onderdelen", "volledig compleet",
    ]
    if any(kw in text for kw in cib_keywords):
        return "CIB"

    return "unknown"


def _get_price_type(listing) -> str:
    """Map Marktplaats PriceType enum to our internal type string."""
    pt = listing.price_type
    if pt in (PriceType.BID, PriceType.BID_FROM):
        return "bidding"
    if pt == PriceType.FREE:
        return "free"
    return "fixed"


def _get_image_url(listing) -> str:
    """Extract medium image URL from listing._images list."""
    try:
        images = listing._images  # list of ListingFirstImage
        if images:
            return images[0].medium or ""
    except Exception:
        pass
    return ""


def _fetch_current_bid(url: str) -> Optional[float]:
    """Fetch listing page and extract current highest bid."""
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
        text = soup.get_text(" ", strip=True)
        patterns = [
            r"[Hh]oogste\s+bieding[:\s]+[€EUR\s]*([0-9.,]+)",
            r"[Hh]uidige\s+bieding[:\s]+[€EUR\s]*([0-9.,]+)",
            r"[Bb]ieding[:\s]+[€EUR\s]*([0-9.,]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    return float(m.group(1).replace(".", "").replace(",", "."))
                except ValueError:
                    continue
        return None
    except Exception:
        return None


def _parse_listing(listing, set_number: str, seen: dict, today: str) -> Optional[dict]:
    """Convert a Marktplaats Listing object into a serializable dict."""
    try:
        listing_id = str(listing.id)
        title = str(listing.title or "")
        description = str(listing.description or "")[:600]
        price = float(listing.price or 0)
        price_type = _get_price_type(listing)
        image_url = _get_image_url(listing)

        seller_name = listing.seller.name if listing.seller else ""
        location_str = listing.location.city if listing.location else ""

        # listing.date is a datetime object or None
        date_str = listing.date.date().isoformat() if listing.date else ""
        days = _days_since(listing.date)

        url = str(listing.link or f"https://www.marktplaats.nl/v/{listing_id}")
        condition = _classify_condition(title, description)

        prev = seen.get(listing_id)
        first_seen = prev["first_seen"] if prev else today
        price_changed = bool(prev and prev.get("price") != price and prev.get("price") is not None)
        previous_price = prev.get("price") if price_changed else None

        seen[listing_id] = {
            "first_seen": first_seen,
            "last_seen": today,
            "price": price,
            "title": title[:80],
            "set_number": set_number,
        }

        return {
            "id": listing_id,
            "set_number": set_number,
            "title": title,
            "price": price,
            "price_type": price_type,
            "current_bid": None,
            "ask_price": price,
            "condition_category": condition,
            "description": description,
            "location": location_str or "",
            "url": url,
            "image_url": image_url,
            "date_posted": date_str,
            "days_listed": days,
            "seller_name": seller_name or "",
            "first_seen": first_seen,
            "price_changed": price_changed,
            "previous_price": previous_price,
            "source": "marktplaats",
        }
    except Exception as e:
        print(f"[Marktplaats] Parse error for listing: {e}")
        return None


def scrape_set(set_number: str, name: str) -> list[dict]:
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

    name_words = [w for w in name.split() if len(w) > 2][:3]
    name_query = " ".join(name_words)
    queries = list(dict.fromkeys([f"{set_number} lego", f"lego {name_query}"]))

    seen_ids: set[str] = set()
    results: list[dict] = []

    for query in queries:
        try:
            search = SearchQuery(query, limit=30)
            raw_listings = search.get_listings() or []
            time.sleep(1.5)

            for raw in raw_listings:
                parsed = _parse_listing(raw, set_number, seen, today)
                if not parsed or parsed["id"] in seen_ids:
                    continue

                # Relevance check: title must contain set number OR a key name word
                title_lower = parsed["title"].lower()
                set_in_title = set_number in title_lower
                name_in_title = any(
                    w.lower() in title_lower
                    for w in name.split()
                    if len(w) > 3
                )
                if set_in_title or name_in_title:
                    seen_ids.add(parsed["id"])
                    results.append(parsed)

        except Exception as e:
            print(f"[Marktplaats] Error scraping '{query}': {e}")

    # Fetch current bids (max 10 per set to limit HTTP requests)
    bidding = [r for r in results if r["price_type"] == "bidding"][:10]
    for item in bidding:
        bid = _fetch_current_bid(item["url"])
        item["current_bid"] = bid
        time.sleep(0.5)

    _save_seen_deals(seen)
    return results


def scrape_all_sets(lego_sets: list[dict]) -> dict[str, list[dict]]:
    """
    Scrape all LEGO sets and return dict of set_number -> list of listing dicts.
    Also saves results to data/marktplaats_deals.json.
    """
    results: dict[str, list[dict]] = {}

    for i, lego_set in enumerate(lego_sets, 1):
        set_number = lego_set["set_number"]
        name = lego_set["name"]
        print(f"[Marktplaats] [{i}/{len(lego_sets)}] {set_number}: {name}")
        listings = scrape_set(set_number, name)
        results[set_number] = listings
        print(f"  → {len(listings)} listings found")
        time.sleep(0.5)

    _save_deals_data(results)
    return results


def _save_deals_data(results: dict[str, list[dict]]) -> None:
    DEALS_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scraped_at": datetime.now().isoformat(),
        "sets": results,
    }
    DEALS_DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def load_deals_data() -> dict:
    if DEALS_DATA_PATH.exists():
        try:
            return json.loads(DEALS_DATA_PATH.read_text())
        except Exception:
            return {}
    return {}
