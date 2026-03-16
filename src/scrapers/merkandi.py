"""
Merkandi.nl scraper.

Merkandi is a B2B wholesale marketplace for liquidation, overstock,
and clearance goods. Public listings are visible without login.
"""

import time
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup


@dataclass
class MerkandiOffer:
    id: str
    title: str
    price: float
    retail_value: float
    quantity: int
    unit: str  # "pallet", "lot", "piece"
    category: str
    condition: str
    country: str
    url: str
    image_url: str
    source: str = "merkandi"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

BASE_URL = "https://merkandi.nl"

# Categories relevant for Vinted resale
SEARCH_CATEGORIES = [
    "/nl/aanbiedingen/dames-kleding",
    "/nl/aanbiedingen/heren-kleding",
    "/nl/aanbiedingen/schoenen",
    "/nl/aanbiedingen/sieraden-horloges",
    "/nl/aanbiedingen/tassen-accessoires",
    "/nl/aanbiedingen/speelgoed",
    "/nl/aanbiedingen/elektronica",
]


def _parse_offer(card) -> Optional[MerkandiOffer]:
    """Parse a Merkandi offer card."""
    try:
        link = card.find("a", href=True)
        if not link:
            return None

        href = link["href"]
        url = href if href.startswith("http") else BASE_URL + href
        offer_id = href.split("/")[-1] or href.split("/")[-2]

        title_el = card.find(["h2", "h3"]) or card.find(
            class_=lambda c: c and "title" in c.lower()
        )
        title = title_el.get_text(strip=True) if title_el else "Onbekend"

        price = 0.0
        price_strings = card.find_all(string=lambda t: t and ("€" in t or "EUR" in t))
        for s in price_strings:
            try:
                clean = s.replace("€", "").replace("EUR", "").replace(",", ".").strip()
                price = float("".join(c for c in clean if c.isdigit() or c == "."))
                if price > 0:
                    break
            except ValueError:
                continue

        img = card.find("img")
        image_url = ""
        if img:
            image_url = img.get("src") or img.get("data-src") or ""
            if image_url.startswith("/"):
                image_url = BASE_URL + image_url

        return MerkandiOffer(
            id=offer_id,
            title=title,
            price=price,
            retail_value=0.0,
            quantity=1,
            unit="lot",
            category="",
            condition="",
            country="NL",
            url=url,
            image_url=image_url,
        )
    except Exception:
        return None


def scrape_merkandi(max_offers: int = 30) -> list[MerkandiOffer]:
    """
    Scrape Merkandi for wholesale/liquidation offers.

    Returns:
        List of MerkandiOffer objects.
    """
    results: list[MerkandiOffer] = []
    seen_ids: set[str] = set()

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        for category_path in SEARCH_CATEGORIES:
            if len(results) >= max_offers:
                break
            url = BASE_URL + category_path
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "lxml")

                cards = (
                    soup.find_all(class_=lambda c: c and "offer" in c.lower())
                    or soup.find_all(class_=lambda c: c and "product" in c.lower())
                    or soup.find_all(class_=lambda c: c and "item" in c.lower())
                    or soup.find_all("article")
                )

                for card in cards:
                    offer = _parse_offer(card)
                    if not offer or offer.id in seen_ids:
                        continue
                    seen_ids.add(offer.id)
                    results.append(offer)
                    if len(results) >= max_offers:
                        break

                time.sleep(2.0)
            except Exception as e:
                print(f"[Merkandi] Error on {url}: {e}")
                continue

    return results
