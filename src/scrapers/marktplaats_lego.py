"""
Marktplaats.nl LEGO scraper.

Per LEGO set: searches by set number only ("lego {set_number}").
- Set number must appear in listing title, else rejected + logged
- Price outside [20%, 300%] of retail price → rejected + logged
- Incomplete condition → excluded + logged
- Tracks listing lifecycle in SQLite to detect disappearances (sold proxy)
- For bidding listings: fetches current highest bid from listing page
"""

import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

try:
    from marktplaats import SearchQuery, PriceType
    _MARKTPLAATS_AVAILABLE = True
except ImportError:
    _MARKTPLAATS_AVAILABLE = False

DEALS_DATA_PATH = Path("data/marktplaats_deals.json")

MIN_PRICE_RATIO = 0.20
MAX_PRICE_RATIO = 3.00


def _days_since(dt: Optional[datetime]) -> int:
    if not dt:
        return 0
    try:
        d = dt if isinstance(dt, date) else dt.date()
        return (datetime.now().date() - d).days
    except Exception:
        return 0


def _get_price_type(listing) -> str:
    pt = listing.price_type
    if pt in (PriceType.BID, PriceType.BID_FROM):
        return "bidding"
    if pt == PriceType.FREE:
        return "free"
    return "fixed"


def _get_image_url(listing) -> str:
    try:
        images = listing._images
        if images:
            return images[0].medium or ""
    except Exception:
        pass
    return ""


def _fetch_current_bid(url: str) -> Optional[float]:
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


def scrape_set(
    set_number: str,
    name: str,
    retail_price: Optional[float] = None,
) -> list[dict]:
    """
    Scrape Marktplaats for a single LEGO set using 'lego {set_number}' only.
    Validates, classifies, tracks lifecycle in SQLite, logs rejections.
    """
    if not _MARKTPLAATS_AVAILABLE:
        print("[Marktplaats] Package not installed. Run: pip install marktplaats")
        return []

    from src.db import init_db, upsert_listing, mark_disappeared, log_rejection
    from src.analysis.condition_classifier import classify_condition

    init_db()
    today = datetime.now().date().isoformat()

    min_price = (retail_price * MIN_PRICE_RATIO) if retail_price else 0.0
    max_price = (retail_price * MAX_PRICE_RATIO) if retail_price else float("inf")

    seen_ids: set[str] = set()
    results: list[dict] = []

    query = f"lego {set_number}"
    try:
        search = SearchQuery(query, limit=50)
        raw_listings = search.get_listings() or []
        time.sleep(1.5)

        for raw in raw_listings:
            try:
                listing_id = str(raw.id)
                title = str(raw.title or "")
                description = str(raw.description or "")[:600]
                price = float(raw.price or 0)
                price_type = _get_price_type(raw)
                image_url = _get_image_url(raw)
                seller_name = raw.seller.name if raw.seller else ""
                location_str = raw.location.city if raw.location else ""

                if raw.date:
                    d = raw.date if isinstance(raw.date, date) else raw.date.date()
                    date_str = d.isoformat()
                else:
                    date_str = ""
                days = _days_since(raw.date)
                url = str(raw.link or f"https://www.marktplaats.nl/v/{listing_id}")

            except Exception as e:
                print(f"[Marktplaats] Parse error: {e}")
                continue

            if listing_id in seen_ids:
                continue

            # Set number must be in title
            if set_number not in title:
                log_rejection(
                    "marktplaats", set_number, listing_id, title, price,
                    "low_confidence", f"'{set_number}' not found in title"
                )
                continue

            if price <= 0 and price_type != "free":
                log_rejection("marktplaats", set_number, listing_id, title, price,
                              "invalid_price", "price is zero")
                continue

            if retail_price and price > 0 and price < min_price:
                log_rejection(
                    "marktplaats", set_number, listing_id, title, price,
                    "price_too_low",
                    f"€{price:.0f} < {MIN_PRICE_RATIO*100:.0f}% of retail €{retail_price:.0f}",
                    image_url=image_url,
                    url=url,
                )
                continue

            if retail_price and price > max_price:
                log_rejection(
                    "marktplaats", set_number, listing_id, title, price,
                    "price_too_high",
                    f"€{price:.0f} > {MAX_PRICE_RATIO*100:.0f}% of retail €{retail_price:.0f}"
                )
                continue

            condition = classify_condition(title, description)
            if condition == "incomplete":
                log_rejection(
                    "marktplaats", set_number, listing_id, title, price,
                    "incomplete", "condition classified as incomplete (cat C)"
                )
                continue

            seen_ids.add(listing_id)

            is_reserved = "gereserveerd" in title.lower() or "gereserveerd" in description.lower()

            upsert_listing(
                listing_id=listing_id,
                platform="marktplaats",
                set_number=set_number,
                title=title,
                price=price,
                condition_category=condition,
                url=url,
                image_url=image_url,
                seller_id="",
                today=today,
                match_confidence=0.95,
                is_reserved=is_reserved,
            )

            if is_reserved:
                print(f"  [Gereserveerd] {title[:60]}")

            results.append({
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
                "source": "marktplaats",
                "is_reserved": is_reserved,
            })

    except Exception as e:
        print(f"[Marktplaats] Error scraping '{query}': {e}")

    # Fetch current bids (max 10 per set)
    for item in [r for r in results if r["price_type"] == "bidding"][:10]:
        bid = _fetch_current_bid(item["url"])
        item["current_bid"] = bid
        time.sleep(0.5)

    disappeared = mark_disappeared("marktplaats", set_number, seen_ids, today)
    if disappeared:
        print(f"  [Lifecycle] {disappeared} Marktplaats listings disappeared → sold proxy")

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
        retail_price = lego_set.get("retail_price")
        print(f"[Marktplaats] [{i}/{len(lego_sets)}] {set_number}: {name}")
        listings = scrape_set(set_number, name, retail_price)
        results[set_number] = listings
        print(f"  → {len(listings)} valid listings found")
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
