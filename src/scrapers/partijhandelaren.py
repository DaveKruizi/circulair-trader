"""
PartijHandelaren.nl scraper.

Dutch platform for buying/selling restpartijen (remainder stock),
stocklots, and bankruptcy goods. ~12,500 unique visitors/month.
"""

import time
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup


@dataclass
class PartijhandeListing:
    id: str
    title: str
    price: float
    description: str
    category: str
    quantity: str
    location: str
    url: str
    image_url: str
    date_posted: str
    source: str = "partijhandelaren"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9",
}

BASE_URL = "https://www.partijhandelaren.nl"
SEARCH_URL = f"{BASE_URL}/partijhandel/zoeken/"


def _parse_listing(card) -> Optional[PartijhandeListing]:
    """Parse a listing card from PartijHandelaren."""
    try:
        link = card.find("a", href=True)
        if not link:
            return None

        href = link["href"]
        url = href if href.startswith("http") else BASE_URL + href
        listing_id = href.rstrip("/").split("/")[-1]

        title_el = card.find(["h2", "h3"]) or card.find(
            class_=lambda c: c and "title" in c.lower()
        )
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)

        price = 0.0
        price_strings = card.find_all(string=lambda t: t and "€" in t)
        for s in price_strings:
            try:
                clean = s.replace("€", "").replace(",", ".").strip()
                price = float("".join(c for c in clean if c.isdigit() or c == "."))
                if price > 0:
                    break
            except ValueError:
                continue

        desc_el = card.find(class_=lambda c: c and "desc" in c.lower())
        description = desc_el.get_text(strip=True)[:300] if desc_el else ""

        img = card.find("img")
        image_url = ""
        if img:
            image_url = img.get("src") or img.get("data-src") or ""
            if image_url.startswith("/"):
                image_url = BASE_URL + image_url

        return PartijhandeListing(
            id=listing_id,
            title=title,
            price=price,
            description=description,
            category="",
            quantity="",
            location="Nederland",
            url=url,
            image_url=image_url,
            date_posted="",
        )
    except Exception:
        return None


def scrape_partijhandelaren(max_listings: int = 20) -> list[PartijhandeListing]:
    """
    Scrape PartijHandelaren for recent listings.

    Returns:
        List of PartijhandeListing objects.
    """
    results: list[PartijhandeListing] = []
    seen_ids: set[str] = set()

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        try:
            resp = client.get(SEARCH_URL)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            cards = (
                soup.find_all(class_=lambda c: c and "partij" in c.lower())
                or soup.find_all(class_=lambda c: c and "listing" in c.lower())
                or soup.find_all(class_=lambda c: c and "item" in c.lower())
                or soup.find_all("article")
                or soup.find_all("li", class_=True)
            )

            for card in cards[:max_listings * 2]:
                listing = _parse_listing(card)
                if not listing or listing.id in seen_ids:
                    continue
                seen_ids.add(listing.id)
                results.append(listing)
                if len(results) >= max_listings:
                    break

            time.sleep(1.5)
        except Exception as e:
            print(f"[PartijHandelaren] Error: {e}")

    return results
