"""
Onlineveilingmeester.nl scraper.

Dutch auction platform for government surplus, bankruptcies,
and business liquidations. New auctions weekly.

The site uses JavaScript rendering for some sections but
the main auction listing is server-rendered.
"""

import time
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup


@dataclass
class OVMLot:
    id: str
    title: str
    current_bid: float
    start_bid: float
    end_date: str
    auction_title: str
    category: str
    location: str
    url: str
    image_url: str
    lot_count: int  # how many lots in this auction
    source: str = "onlineveilingmeester"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9",
    "Referer": "https://www.onlineveilingmeester.nl/",
}

BASE_URL = "https://www.onlineveilingmeester.nl"
AUCTIONS_URL = f"{BASE_URL}/nl"


def _parse_auction_card(card) -> Optional[OVMLot]:
    """Parse an auction/lot card."""
    try:
        link = card.find("a", href=True)
        if not link:
            return None

        href = link["href"]
        url = href if href.startswith("http") else BASE_URL + href
        lot_id = href.rstrip("/").split("/")[-1]

        # Title
        title_el = (
            card.find(["h2", "h3", "h4"])
            or card.find(class_=lambda c: c and "title" in c.lower())
        )
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)

        # Bid/price
        current_bid = 0.0
        bid_el = card.find(class_=lambda c: c and ("bid" in c.lower() or "price" in c.lower() or "bod" in c.lower()))
        if bid_el:
            bid_text = bid_el.get_text(strip=True)
            try:
                clean = bid_text.replace("€", "").replace(",", ".").strip()
                current_bid = float("".join(c for c in clean if c.isdigit() or c == "."))
            except ValueError:
                pass

        # Date
        date_el = card.find(class_=lambda c: c and ("date" in c.lower() or "time" in c.lower() or "datum" in c.lower()))
        end_date = date_el.get_text(strip=True) if date_el else ""

        # Image
        img = card.find("img")
        image_url = ""
        if img:
            image_url = img.get("src") or img.get("data-src") or ""
            if image_url.startswith("/"):
                image_url = BASE_URL + image_url

        return OVMLot(
            id=lot_id,
            title=title,
            current_bid=current_bid,
            start_bid=0.0,
            end_date=end_date,
            auction_title="",
            category="",
            location="Nederland",
            url=url,
            image_url=image_url,
            lot_count=0,
        )
    except Exception:
        return None


def scrape_onlineveilingmeester(max_lots: int = 30) -> list[OVMLot]:
    """
    Scrape Onlineveilingmeester for active auction lots.

    Returns:
        List of OVMLot objects.
    """
    results: list[OVMLot] = []
    seen_ids: set[str] = set()

    urls_to_try = [
        AUCTIONS_URL,
        f"{BASE_URL}/nl/veilingen",
        f"{BASE_URL}/nl/kavels",
    ]

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        for url in urls_to_try:
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    print(f"[OVM] Got {resp.status_code} on {url}")
                    time.sleep(2.0)
                    continue

                soup = BeautifulSoup(resp.text, "lxml")

                # OVM uses various card/tile layouts
                cards = (
                    soup.find_all(class_=lambda c: c and "auction" in c.lower())
                    or soup.find_all(class_=lambda c: c and "veiling" in c.lower())
                    or soup.find_all(class_=lambda c: c and "kavel" in c.lower())
                    or soup.find_all(class_=lambda c: c and "lot" in c.lower())
                    or soup.find_all(class_=lambda c: c and "card" in c.lower())
                    or soup.find_all("article")
                )

                for card in cards[:max_lots * 2]:
                    lot = _parse_auction_card(card)
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
                print(f"[OVM] Error on {url}: {e}")
                continue

    if not results:
        print("[OVM] No results found. Site may require JavaScript rendering.")
        print("[OVM] Consider enabling playwright-based scraping for this source.")

    return results
