"""
Vinted scraper — trend analysis via public listings.

Uses the vinted-scraper PyPI package which wraps Vinted's internal API.
Collects active listings to derive:
- Which categories/products appear frequently
- Average asking prices per category
- Listing age (proxy for demand: old = low demand)
- Favorites count (proxy for interest)

Note: Vinted has no official public API. This uses the unofficial API
that the app itself uses. It may break if Vinted changes their API.
Use responsibly and respect rate limits.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from vinted_scraper import VintedScraper


# ── Playwright-gebaseerde sessie-cookie fetch ─────────────────────────────────
# Vinted blokkeert httpx-gebaseerde cookie fetches (bot-detectie op HTTP-niveau).
# Playwright simuleert een echte browser en ontwijkt deze blokkade.
# Cookie wordt één keer opgehaald en gecached voor de hele run.

_session_cookies: dict[str, Optional[dict]] = {}  # domain → {"access_token_web": "..."}


def _fetch_cookie_via_playwright(domain: str) -> Optional[dict]:
    """Open de Vinted homepage in een headless browser en pak de access_token_web cookie."""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        print("[Vinted] Playwright niet beschikbaar — cookie fetch overgeslagen.")
        return None

    print(f"[Vinted] Sessie-cookie ophalen via Playwright voor {domain}...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="nl-NL",
            )
            page = context.new_page()
            page.goto(domain, wait_until="domcontentloaded", timeout=20_000)
            # Geef Vinted 3s om cookies te zetten na het laden
            page.wait_for_timeout(3_000)
            cookies = context.cookies()
            browser.close()

        for c in cookies:
            if c["name"] == "access_token_web":
                print("[Vinted] Sessie-cookie succesvol opgehaald via Playwright.")
                return {"access_token_web": c["value"]}

        print("[Vinted] access_token_web niet gevonden in Playwright cookies.")
        return None
    except PlaywrightTimeout:
        print(f"[Vinted] Playwright timeout bij ophalen cookie voor {domain}.")
        return None
    except Exception as e:
        print(f"[Vinted] Playwright cookie fetch mislukt: {e}")
        return None


def _get_session_cookie(domain: str) -> Optional[dict]:
    """Geeft de gecachede cookie terug, of haalt hem op als hij nog niet bestaat."""
    if domain not in _session_cookies:
        _session_cookies[domain] = _fetch_cookie_via_playwright(domain)
    return _session_cookies[domain]


@dataclass
class VintedListing:
    id: str
    title: str
    price: float
    currency: str
    brand: str
    category: str
    size: str
    condition: str
    favorites_count: int
    views_count: int
    created_at: str
    url: str
    photo_url: str
    # Derived field: estimated days listed (approximate, based on listing ID gap)
    days_listed: Optional[int] = None


@dataclass
class VintedTrend:
    category: str
    search_term: str
    avg_price: float
    min_price: float
    max_price: float
    listing_count: int
    avg_favorites: float
    # Listings with high favorites relative to listing age = high demand signal
    demand_score: float
    sample_listings: list[VintedListing] = field(default_factory=list)


# Categories and search terms to monitor for resale potential.
# Breed spectrum: van kinderproducten tot merkkleding, sneakers en elektronica.
SEARCH_TARGETS = [
    # ── Kinderproducten ───────────────────────────────────────────
    {"term": "kinderkleding", "category": "Kinderkleding"},
    {"term": "babykleding", "category": "Kinderkleding"},
    {"term": "kinderschoenen", "category": "Kinderkleding"},
    {"term": "speelgoed", "category": "Speelgoed"},
    {"term": "lego", "category": "Speelgoed"},
    {"term": "playmobil", "category": "Speelgoed"},
    {"term": "kinderboeken", "category": "Kinderboeken"},
    # ── Dameskleding ─────────────────────────────────────────────
    {"term": "dameskleding", "category": "Dameskleding"},
    {"term": "zara", "category": "Dameskleding"},
    {"term": "h&m kleding", "category": "Dameskleding"},
    {"term": "jurk", "category": "Dameskleding"},
    {"term": "winterjas dames", "category": "Dameskleding"},
    # ── Herenkleding ─────────────────────────────────────────────
    {"term": "herenkleding", "category": "Herenkleding"},
    {"term": "spijkerbroek heren", "category": "Herenkleding"},
    {"term": "hoodie", "category": "Herenkleding"},
    # ── Schoenen ─────────────────────────────────────────────────
    {"term": "sneakers", "category": "Schoenen"},
    {"term": "nike schoenen", "category": "Schoenen"},
    {"term": "adidas schoenen", "category": "Schoenen"},
    {"term": "damesschoenen", "category": "Schoenen"},
    # ── Sportkledij ───────────────────────────────────────────────
    {"term": "sportkleding", "category": "Sport"},
    {"term": "sportschoenen", "category": "Sport"},
    # ── Tassen & Accessoires ─────────────────────────────────────
    {"term": "handtas", "category": "Tassen"},
    {"term": "rugzak", "category": "Tassen"},
    # ── Elektronica ───────────────────────────────────────────────
    {"term": "smartphone", "category": "Elektronica"},
    {"term": "koptelefoon", "category": "Elektronica"},
    {"term": "tablet", "category": "Elektronica"},
    # ── Vintage & Retro ───────────────────────────────────────────
    {"term": "vintage kleding", "category": "Vintage"},
    {"term": "vintage jas", "category": "Vintage"},
    {"term": "retro kleding", "category": "Vintage"},
]


def _parse_listing(item) -> Optional[VintedListing]:
    """Parse a raw Vinted item into a VintedListing."""
    try:
        price_raw = getattr(item, "price", None)
        price = float(price_raw) if price_raw else 0.0
        if price < 1:
            return None

        return VintedListing(
            id=str(getattr(item, "id", "")),
            title=str(getattr(item, "title", "")),
            price=price,
            currency=str(getattr(item, "currency", "EUR")),
            brand=str(getattr(item, "brand_title", "") or ""),
            category=str(getattr(item, "category_title", "") or ""),
            size=str(getattr(item, "size_title", "") or ""),
            condition=str(getattr(item, "status", "") or ""),
            favorites_count=int(getattr(item, "favourite_count", 0) or 0),
            views_count=int(getattr(item, "view_count", 0) or 0),
            created_at=str(getattr(item, "created_at_ts", "") or ""),
            url=str(getattr(item, "url", "") or ""),
            photo_url=(
                item.photos[0].url
                if getattr(item, "photos", None)
                else ""
            ),
        )
    except Exception:
        return None


def _parse_created_at(value: str) -> Optional[datetime]:
    """Parse a Vinted created_at value — Unix timestamp or ISO string."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (ValueError, OSError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(value[:19], fmt[:len(fmt)])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _compute_demand_score(listings: list[VintedListing]) -> float:
    """
    Score 0–10. Hogere score = meer vraag.

    Combineert twee signalen:
    - Velocity (60 %): favorites per dag — snel oplopende favorieten op recente
      listings wijzen op actieve vraag.
    - Populariteit (40 %): absolute gem. favorites — tijdloze indicator van interesse.

    Calibratie: 0,5 fav/dag ≈ score 5 bij velocity-component.
    """
    if not listings:
        return 0.0

    now = datetime.now(timezone.utc)
    velocities: list[float] = []

    for lst in listings:
        dt = _parse_created_at(lst.created_at)
        if dt:
            days = max(1.0, (now - dt).total_seconds() / 86400)
        else:
            days = 7.0  # conservatieve aanname als timestamp ontbreekt
        velocities.append(lst.favorites_count / days)

    avg_velocity = sum(velocities) / len(velocities)
    avg_fav = sum(l.favorites_count for l in listings) / len(listings)

    velocity_score = min(10.0, avg_velocity * 20)   # 0,5 fav/dag → 10
    fav_score = min(10.0, avg_fav * 1.5)             # 6,7 favs gem → 10

    return round(0.6 * velocity_score + 0.4 * fav_score, 1)


# Dutch stop words to strip when building a product-specific search query
_STOP_WORDS_NL = {
    "en", "de", "het", "een", "van", "in", "op", "met", "voor", "aan", "te",
    "er", "of", "om", "bij", "uit", "door", "over", "tot", "als", "zo", "ook",
    "nog", "al", "is", "zijn", "was", "heeft", "hebben", "wordt", "worden",
    "niet", "maar", "dat", "die", "dit", "den", "der", "des", "se", "zo",
}


def _clean_product_title(title: str) -> str:
    """Strip stop words and punctuation; return up to 4 meaningful keywords."""
    import re
    words = re.sub(r"[^\w\s]", " ", title.lower()).split()
    meaningful = [w for w in words if w not in _STOP_WORDS_NL and len(w) > 2]
    return " ".join(meaningful[:4])


def _is_session_error(e: Exception) -> bool:
    return "session cookie" in str(e).lower()


def search_vinted_for_product(
    title: str,
    buy_price: float = 0,
    domain: str = "https://www.vinted.nl",
    max_results: int = 20,
    min_price: float = 1.0,
) -> Optional["VintedTrend"]:
    """
    Search Vinted for a *specific* product by its title.

    Cleans the title to 2–4 keywords and queries Vinted directly so that
    price data comes from real listings of the same product rather than a
    generic category.

    Args:
        title:       Product title from the buying platform.
        buy_price:   Known buy price; used to narrow the price filter.
        domain:      Vinted domain to search (default: vinted.nl).
        max_results: Max listings to retrieve.
        min_price:   Hard floor on listing price.

    Returns:
        VintedTrend with real listing data, or None if fewer than 3 results.
    """
    search_term = _clean_product_title(title)
    if not search_term:
        return None

    params: dict = {
        "search_text": search_term,
        "per_page": max_results,
        "order": "newest_first",
    }
    if buy_price > 0:
        params["price_from"] = max(min_price, buy_price * 0.8)
        params["price_to"] = buy_price * 6
    else:
        params["price_from"] = min_price

    cookie = _get_session_cookie(domain)
    if cookie is None:
        return None

    backoff = 2.0
    for attempt in range(3):
        try:
            scraper = VintedScraper(domain, session_cookie=cookie)
            raw_items = scraper.search(params)
            listings = [lst for item in (raw_items or []) if (lst := _parse_listing(item))]

            if len(listings) < 3:
                return None

            prices = [l.price for l in listings]
            return VintedTrend(
                category="product-specifiek",
                search_term=search_term,
                avg_price=round(sum(prices) / len(prices), 2),
                min_price=round(min(prices), 2),
                max_price=round(max(prices), 2),
                listing_count=len(listings),
                avg_favorites=round(
                    sum(l.favorites_count for l in listings) / len(listings), 1
                ),
                demand_score=_compute_demand_score(listings),
                sample_listings=sorted(
                    listings, key=lambda l: l.favorites_count, reverse=True
                )[:5],
            )
        except Exception as e:
            if _is_session_error(e):
                # Cookie verlopen — vernieuw via Playwright en probeer nog één keer
                _session_cookies.pop(domain, None)
                cookie = _get_session_cookie(domain)
                if cookie is None:
                    return None
                continue
            err = str(e).lower()
            if any(kw in err for kw in ("429", "rate", "too many", "blocked", "forbidden", "406")):
                if attempt < 2:
                    print(f"[Vinted] Rate limited voor '{search_term}', wacht {backoff:.0f}s... (poging {attempt + 1}/3)")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
            print(f"[Vinted] Per-product search mislukt voor '{search_term}': {e}")
            return None

    return None


def scrape_vinted_trends(
    domains: list[str] = None,
    max_per_term: int = 30,
    min_price: float = 5.0,
) -> list[VintedTrend]:
    """
    Scrape Vinted for trending products and price data.

    Args:
        domains: Vinted domains to scrape. Defaults to NL + international.
        max_per_term: Max listings to fetch per search term.
        min_price: Minimum price to include in analysis.

    Returns:
        List of VintedTrend objects sorted by demand_score desc.
    """
    if domains is None:
        domains = ["https://www.vinted.nl", "https://www.vinted.com"]

    trends: list[VintedTrend] = []

    for target in SEARCH_TARGETS:
        term = target["term"]
        category = target["category"]
        all_listings: list[VintedListing] = []

        for domain in domains:
            cookie = _get_session_cookie(domain)
            if cookie is None:
                continue
            try:
                scraper = VintedScraper(domain, session_cookie=cookie)
                params = {
                    "search_text": term,
                    "price_from": min_price,
                    "per_page": max_per_term,
                    "order": "newest_first",
                }
                raw_items = scraper.search(params)
                for item in raw_items or []:
                    listing = _parse_listing(item)
                    if listing:
                        all_listings.append(listing)
                # Polite rate limiting
                time.sleep(1.5)
            except Exception as e:
                if _is_session_error(e):
                    # Cookie verlopen — vernieuw en sla dit domein over voor deze term
                    _session_cookies.pop(domain, None)
                    print(f"[Vinted] Cookie verlopen voor {domain}, wordt vernieuwd bij volgende aanroep.")
                else:
                    print(f"[Vinted] Error scraping '{term}' on {domain}: {e}")
                continue

        if not all_listings:
            continue

        prices = [l.price for l in all_listings]
        trend = VintedTrend(
            category=category,
            search_term=term,
            avg_price=round(sum(prices) / len(prices), 2),
            min_price=round(min(prices), 2),
            max_price=round(max(prices), 2),
            listing_count=len(all_listings),
            avg_favorites=round(
                sum(l.favorites_count for l in all_listings) / len(all_listings), 1
            ),
            demand_score=_compute_demand_score(all_listings),
            # Keep top 5 most-favorited as samples
            sample_listings=sorted(
                all_listings, key=lambda l: l.favorites_count, reverse=True
            )[:5],
        )
        trends.append(trend)

    return sorted(trends, key=lambda t: t.demand_score, reverse=True)
