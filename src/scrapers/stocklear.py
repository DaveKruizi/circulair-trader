"""
Stocklear.nl scraper.

Stocklear is a B2B auction platform for overstock and returns,
including Bol.com return pallets.

The site requires authentication for full access, but some listings
are visible on public category pages. We scrape what's publicly available.
"""

import time
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup


@dataclass
class StocklearLot:
    id: str
    title: str
    current_price: float
    retail_value: float
    category: str
    condition: str  # A+, A, B, C, D
    quantity: int
    url: str
    image_url: str
    end_date: str
    source: str = "stocklear"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9",
}

BASE_URL = "https://www.stocklear.nl"


def _parse_lot(card) -> Optional[StocklearLot]:
    """Parse a lot card from Stocklear HTML."""
    try:
        link = card.find("a", href=True)
        url = (BASE_URL + link["href"]) if link else ""
        lot_id = (link["href"].split("/")[-1] if link else "")

        title_el = card.find(["h2", "h3", "h4"]) or card.find(
            class_=lambda c: c and "title" in c.lower()
        )
        title = title_el.get_text(strip=True) if title_el else "Onbekend"

        # Try to find price
        price = 0.0
        price_els = card.find_all(string=lambda t: t and "€" in t)
        for el in price_els:
            try:
                clean = el.replace("€", "").replace(",", ".").strip()
                price = float("".join(c for c in clean if c.isdigit() or c == "."))
                break
            except ValueError:
                continue

        img = card.find("img")
        image_url = img.get("src", "") if img else ""
        if image_url and image_url.startswith("/"):
            image_url = BASE_URL + image_url

        return StocklearLot(
            id=lot_id or url,
            title=title,
            current_price=price,
            retail_value=0.0,
            category="",
            condition="",
            quantity=1,
            url=url,
            image_url=image_url,
            end_date="",
        )
    except Exception:
        return None


def scrape_stocklear(max_lots: int = 20) -> list[StocklearLot]:
    """
    Scrape Stocklear for available lots.

    Note: Stocklear may require login for full access. This scrapes
    the public catalog pages. If you have an account, consider using
    browser automation (playwright) for better results.

    Returns:
        List of StocklearLot objects.
    """
    results: list[StocklearLot] = []
    seen_ids: set[str] = set()

    urls_to_try = [
        f"{BASE_URL}/nl/veilingen",
        f"{BASE_URL}/nl/catalogus",
        f"{BASE_URL}/nl",
    ]

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        for url in urls_to_try:
            try:
                resp = client.get(url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    cards = (
                        soup.find_all(class_=lambda c: c and "lot" in c.lower())
                        or soup.find_all(class_=lambda c: c and "product" in c.lower())
                        or soup.find_all(class_=lambda c: c and "card" in c.lower())
                        or soup.find_all("article")
                    )
                    for card in cards[:max_lots * 2]:
                        lot = _parse_lot(card)
                        if not lot or lot.id in seen_ids:
                            continue
                        seen_ids.add(lot.id)
                        results.append(lot)
                        if len(results) >= max_lots:
                            break
                    if results:
                        break
                time.sleep(2.0)
            except Exception as e:
                print(f"[Stocklear] Error on {url}: {e}")
                continue

    if not results:
        print("[Stocklear] No public listings found. May require authentication.")

    return results
