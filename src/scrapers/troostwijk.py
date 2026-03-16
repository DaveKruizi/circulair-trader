"""
Troostwijk Auctions scraper (formerly BVA Auctions).

Scrapes active auction lots from troostwijkauctions.com.
Uses httpx + BeautifulSoup since the site uses server-side rendering for listings.
Note: The site uses infinite scroll — we fetch the first page of results.
"""

import time
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup


@dataclass
class TroostwijkLot:
    id: str
    title: str
    current_bid: float
    estimated_value: float
    end_date: str
    location: str
    url: str
    image_url: str
    auction_title: str
    source: str = "troostwijk"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BASE_URL = "https://www.troostwijkauctions.com/nl"

# Categories relevant for Vinted resale (consumer goods, not industrial)
RELEVANT_CATEGORIES = [
    "/nl/veilingen?category=consumer-goods",
    "/nl/veilingen?category=clothing-accessories",
    "/nl/veilingen?category=furniture-interior",
]


def _parse_lot_card(card) -> Optional[TroostwijkLot]:
    """Parse a single lot card from the search results HTML."""
    try:
        link = card.find("a", href=True)
        if not link:
            return None

        url = "https://www.troostwijkauctions.com" + link["href"]
        lot_id = link["href"].split("/")[-1]

        title_el = card.find(class_=lambda c: c and "title" in c.lower())
        title = title_el.get_text(strip=True) if title_el else ""

        if not title:
            title_el = card.find(["h2", "h3", "h4"])
            title = title_el.get_text(strip=True) if title_el else "Onbekend"

        bid_el = card.find(class_=lambda c: c and ("bid" in c.lower() or "price" in c.lower()))
        current_bid = 0.0
        if bid_el:
            bid_text = bid_el.get_text(strip=True).replace("€", "").replace(",", ".").strip()
            try:
                current_bid = float("".join(c for c in bid_text if c.isdigit() or c == "."))
            except ValueError:
                pass

        img = card.find("img")
        image_url = img.get("src", "") if img else ""

        return TroostwijkLot(
            id=lot_id,
            title=title,
            current_bid=current_bid,
            estimated_value=0.0,
            end_date="",
            location="Nederland",
            url=url,
            image_url=image_url,
            auction_title="",
        )
    except Exception:
        return None


def scrape_troostwijk(
    max_lots: int = 30,
    max_current_bid: float = 50.0,
) -> list[TroostwijkLot]:
    """
    Scrape Troostwijk for consumer goods lots under max_current_bid.

    Args:
        max_lots: Maximum number of lots to return.
        max_current_bid: Filter out lots where current bid exceeds this.

    Returns:
        List of TroostwijkLot objects.
    """
    results: list[TroostwijkLot] = []
    seen_ids: set[str] = set()

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        # Try the general auctions page first
        search_url = f"{BASE_URL}/veilingen"
        try:
            resp = client.get(search_url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Look for lot/auction cards — Troostwijk uses various class names
            cards = (
                soup.find_all(class_=lambda c: c and "lot" in c.lower())
                or soup.find_all(class_=lambda c: c and "auction-item" in c.lower())
                or soup.find_all(class_=lambda c: c and "card" in c.lower())
                or soup.find_all("article")
            )

            for card in cards[:max_lots * 2]:
                lot = _parse_lot_card(card)
                if not lot or lot.id in seen_ids:
                    continue
                if lot.current_bid > max_current_bid and lot.current_bid > 0:
                    continue
                seen_ids.add(lot.id)
                results.append(lot)

                if len(results) >= max_lots:
                    break

            time.sleep(2.0)
        except Exception as e:
            print(f"[Troostwijk] Error scraping: {e}")

    return results
