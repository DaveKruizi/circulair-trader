"""
Marktplaats.nl LEGO scraper.

Per LEGO set: searches by set number only ("lego {set_number}").
- Set number must appear in listing title (not just description), else rejected + logged
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

# Detecteer expliciete setnummers in titels (4–6 cijfers, geen jaarnummers zoals 2024)
_SET_NUMBER_RE = re.compile(r'\b([0-9]{4,6})\b')


def _looks_like_set_number(n: str) -> bool:
    """True als n een LEGO-setnummer is (geen jaar zoals 2024/2023)."""
    return not re.match(r'^(19|20)\d{2}$', n)


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
    Scrape Marktplaats for a single LEGO set.
    Runs two queries per set en dedupliceert op listing-ID.

    Accepteercriterium per query-type:

    Nummer-query ("lego {set_number}"):
      - Setnummer MOET in de titel staan.

    Naam-query ("lego {name}"):
      - Als de naam ≥2 significante woorden (≥4 tekens) heeft:
          alle significante woorden moeten in de titel voorkomen.
          (bv. "Lamborghini Revuelto" → ["lamborghini","revuelto"] in titel)
      - Als de naam slechts 1 significant woord heeft (bv. "Corvette",
          "Porsche 911"): te generiek — setnummer verplicht in titel.
          Zo worden meerdere Corvette-/Porsche-sets niet door elkaar gehaald.
    """
    if not _MARKTPLAATS_AVAILABLE:
        print("[Marktplaats] Package not installed. Run: pip install marktplaats")
        return []

    from src.db import init_db, upsert_listing, mark_disappeared, log_rejection
    from src.analysis.condition_classifier import classify_condition
    from src.analysis.content_filters import is_replica, is_accessory, is_bundle

    init_db()
    today = datetime.now().date().isoformat()

    min_price = (retail_price * MIN_PRICE_RATIO) if retail_price else 0.0
    max_price = (retail_price * MAX_PRICE_RATIO) if retail_price else float("inf")

    # Significante woorden uit de setnaam (≥4 tekens), eenmalig berekend.
    # Bij ≤1 significant woord is de naam te generiek → naam-query eist ook setnummer in titel.
    sig_name_words = [w.lower() for w in name.split() if len(w) >= 4]
    generic_name = len(sig_name_words) <= 1  # bv. "Corvette", "Porsche 911"

    seen_ids: set[str] = set()
    results: list[dict] = []
    all_seen_sellers: list[tuple[str, str, str]] = []

    # require_number_in_title=True  → setnummer moet in titel staan
    # require_number_in_title=False → alle significante naamwoorden moeten in titel staan
    queries = [
        (f"lego {set_number}", True),
        (f"lego {name}", True if generic_name else False),
    ]

    for query, require_number_in_title in queries:
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
                    if seller_name and "lego" in title.lower():
                        all_seen_sellers.append((listing_id, seller_name, title))
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

                title_lower = title.lower()
                desc_lower = description.lower()

                # LEGO moet ergens in de advertentie voorkomen
                if "lego" not in title_lower and "lego" not in desc_lower:
                    log_rejection(
                        "marktplaats", set_number, listing_id, title, price,
                        "no_lego_mention", "woord 'lego' ontbreekt in titel en beschrijving"
                    )
                    continue

                # Catawiki: veilingsite met afwijkende advertenties → uitsluiten
                if seller_name.lower() == "catawiki":
                    log_rejection(
                        "marktplaats", set_number, listing_id, title, price,
                        "catawiki_seller", "verkoper is Catawiki (veilingsite)"
                    )
                    continue

                # Speed Champions: goedkope thema-sets die premium-sets vervuilen
                if "speed champions" in title_lower:
                    log_rejection(
                        "marktplaats", set_number, listing_id, title, price,
                        "wrong_theme", "Speed Champions-set in titel — niet het premium model"
                    )
                    continue

                # ── Accepteerfilter ──────────────────────────────────────────
                # Nummer-query: setnummer verplicht in titel.
                if require_number_in_title and set_number not in title:
                    log_rejection(
                        "marktplaats", set_number, listing_id, title, price,
                        "low_confidence", f"'{set_number}' niet gevonden in titel"
                    )
                    continue

                # Naam-query (require_number_in_title=False):
                # - Als de titel een ANDER setnummer bevat → verkeerde set.
                # - Alle significante naamwoorden (≥4 tekens) moeten in de titel staan.
                if not require_number_in_title:
                    title_numbers = {
                        n for n in _SET_NUMBER_RE.findall(title)
                        if _looks_like_set_number(n)
                    }
                    if title_numbers and set_number not in title_numbers:
                        other = ", ".join(sorted(title_numbers)[:3])
                        log_rejection(
                            "marktplaats", set_number, listing_id, title, price,
                            "wrong_set", f"titel bevat ander setnummer ({other}), niet {set_number}"
                        )
                        continue

                    if sig_name_words and not all(w in title_lower for w in sig_name_words):
                        missing = [w for w in sig_name_words if w not in title_lower]
                        log_rejection(
                            "marktplaats", set_number, listing_id, title, price,
                            "low_confidence",
                            f"naam-woorden {missing} niet gevonden in titel (set: '{name}')"
                        )
                        continue

                # Bundel van meerdere sets — prijs onbruikbaar voor één set
                flagged, reason = is_bundle(title, description)
                if flagged:
                    log_rejection(
                        "marktplaats", set_number, listing_id, title, price,
                        "bundle", reason
                    )
                    continue

                # Replica / namaak LEGO
                flagged, kw = is_replica(title, description)
                if flagged:
                    log_rejection(
                        "marktplaats", set_number, listing_id, title, price,
                        "replica", f"namaak-signaal: '{kw}'"
                    )
                    continue

                # Accessoire (verlichtingskit, display-box, etc.)
                flagged, kw = is_accessory(title)
                if flagged:
                    log_rejection(
                        "marktplaats", set_number, listing_id, title, price,
                        "accessory", f"accessoire-signaal: '{kw}'",
                        image_url=image_url,
                        url=url,
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
                    seller_name=seller_name,
                    price_type=price_type,
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

    if seen_ids:
        disappeared = mark_disappeared("marktplaats", set_number, seen_ids, today)
        if disappeared:
            print(f"  [Lifecycle] {disappeared} Marktplaats listings disappeared → sold proxy")
    else:
        print(f"  [Lifecycle] SKIP mark_disappeared voor Marktplaats set {set_number}: "
              f"0 geldige listings (filter te streng of Marktplaats onbereikbaar?)")

    return results, all_seen_sellers


def scrape_all_sets(lego_sets: list[dict]) -> dict[str, list[dict]]:
    """
    Scrape all LEGO sets and return dict of set_number -> list of listing dicts.
    Also saves results to data/marktplaats_deals.json, including seller_lego_counts:
    een dict van seller_name -> aantal unieke LEGO-listings gezien over ALLE zoekopdrachten.
    Dit geeft een brede proxy voor hoeveel LEGO-advertenties een verkoper heeft,
    ook voor sets die we niet specifiek volgen.
    """
    results: dict[str, list[dict]] = {}
    # seller_name -> set van listing_ids met 'lego' in de titel
    seller_lego_seen: dict[str, set] = {}

    for i, lego_set in enumerate(lego_sets, 1):
        set_number = lego_set["set_number"]
        name = lego_set["name"]
        retail_price = lego_set.get("retail_price")
        print(f"[Marktplaats] [{i}/{len(lego_sets)}] {set_number}: {name}")
        listings, all_seen = scrape_set(set_number, name, retail_price)
        results[set_number] = listings
        print(f"  → {len(listings)} valid listings found")

        # Verwerk brede verkoperstelling
        for lid, sname, _title in all_seen:
            if sname:
                seller_lego_seen.setdefault(sname, set()).add(lid)

        time.sleep(0.5)

    # Converteer sets naar aantallen
    seller_lego_counts = {s: len(ids) for s, ids in seller_lego_seen.items()}
    _save_deals_data(results, seller_lego_counts)
    return results


def _save_deals_data(results: dict[str, list[dict]], seller_lego_counts: dict | None = None) -> None:
    DEALS_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scraped_at": datetime.now().isoformat(),
        "sets": results,
        "seller_lego_counts": seller_lego_counts or {},
    }
    DEALS_DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def load_deals_data() -> dict:
    if DEALS_DATA_PATH.exists():
        try:
            return json.loads(DEALS_DATA_PATH.read_text())
        except Exception:
            return {}
    return {}
