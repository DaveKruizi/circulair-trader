"""
Vinted LEGO scraper — weekly price analysis.

Per LEGO set: scrapes Vinted NL, BE, and DE for each condition category.
Calculates average asking price and "stale" price (listings >3 weeks old).
Tracks weekly listing counts to derive velocity trends.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from vinted_scraper import VintedScraper
    _VINTED_AVAILABLE = True
except ImportError:
    _VINTED_AVAILABLE = False

VINTED_PRICES_PATH = Path("data/vinted_prices.json")
VINTED_HISTORY_PATH = Path("data/vinted_price_history.json")

# Platforms to scrape (NL = primary, BE + DE for international pricing)
VINTED_PLATFORMS = [
    "https://www.vinted.nl",
    "https://www.vinted.be",
    "https://www.vinted.de",
]

STALE_DAYS = 21  # listings older than this are considered "stale"


@dataclass
class VintedListing:
    id: str
    title: str
    price: float
    currency: str
    condition: str        # Vinted's own condition label
    platform: str         # "nl", "be", "de"
    url: str
    image_url: str
    created_at: str       # ISO timestamp from Vinted
    days_old: int
    is_stale: bool        # True if older than STALE_DAYS


@dataclass
class SetPriceData:
    """Aggregated Vinted price data for one set + condition category."""
    set_number: str
    condition_category: str   # "NIB", "CIB", "incomplete", "all"
    listing_count: int
    stale_count: int
    avg_ask_price: Optional[float]
    stale_avg_price: Optional[float]
    realistic_sell_price: Optional[float]  # stale avg if available, else regular avg
    min_price: Optional[float]
    max_price: Optional[float]
    platforms: list[str]      # which platforms contributed


def _parse_vinted_listing(raw, platform_domain: str) -> Optional[VintedListing]:
    """Parse a raw Vinted listing object into a VintedListing."""
    try:
        listing_id = str(getattr(raw, "id", "") or "")
        title = str(getattr(raw, "title", "") or "")
        price_raw = getattr(raw, "price", None) or getattr(raw, "price_numeric", None)
        price = float(str(price_raw).replace(",", ".")) if price_raw else 0.0
        currency = str(getattr(raw, "currency", "EUR") or "EUR")

        # Condition from Vinted (may be None)
        condition_obj = getattr(raw, "status", None) or getattr(raw, "condition", None)
        condition = str(condition_obj) if condition_obj else "unknown"

        url_raw = getattr(raw, "url", "") or ""
        url = str(url_raw) if url_raw else ""

        photo = getattr(raw, "photo", None)
        image_url = ""
        if photo:
            image_url = str(
                getattr(photo, "url", "")
                or getattr(photo, "full_size_url", "")
                or ""
            )

        created_raw = getattr(raw, "created_at_ts", None) or getattr(raw, "created_at", None)
        created_at = ""
        days_old = 0
        if created_raw:
            try:
                if isinstance(created_raw, (int, float)):
                    dt = datetime.fromtimestamp(created_raw)
                else:
                    dt = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                created_at = dt.date().isoformat()
                days_old = (datetime.now().date() - dt.date()).days
            except Exception:
                pass

        platform_code = platform_domain.replace("https://www.vinted.", "").split(".")[0]
        is_stale = days_old >= STALE_DAYS

        return VintedListing(
            id=listing_id,
            title=title,
            price=price,
            currency=currency,
            condition=condition,
            platform=platform_code,
            url=url,
            image_url=image_url,
            created_at=created_at,
            days_old=days_old,
            is_stale=is_stale,
        )
    except Exception as e:
        print(f"[Vinted] Parse error: {e}")
        return None


def _is_lego_set(title: str, set_number: str, set_name: str) -> bool:
    """Basic relevance check: title should mention set number or key name words."""
    title_lower = title.lower()
    if set_number.lower() in title_lower:
        return True
    name_words = [w for w in set_name.lower().split() if len(w) > 3]
    return any(w in title_lower for w in name_words[:3])


def _scrape_platform(platform: str, query: str, max_results: int = 80) -> list:
    """Scrape a single Vinted platform for a query. Returns raw listing objects."""
    if not _VINTED_AVAILABLE:
        return []
    try:
        scraper = VintedScraper(platform)
        params = {"search_text": query, "per_page": min(max_results, 96)}
        items = scraper.search(params) or []
        return list(items)[:max_results]
    except Exception as e:
        print(f"[Vinted] Error on {platform} for '{query}': {e}")
        return []


def scrape_set_prices(set_number: str, set_name: str) -> dict[str, SetPriceData]:
    """
    Scrape all Vinted platforms for one LEGO set.
    Returns a dict: condition_category -> SetPriceData.
    Categories: "NIB", "CIB", "incomplete", "unknown", "all"
    """
    all_listings: list[VintedListing] = []

    name_words = [w for w in set_name.split() if len(w) > 2][:3]
    name_query = " ".join(name_words)
    queries = list(dict.fromkeys([f"{set_number} lego", f"lego {name_query}"]))

    for platform in VINTED_PLATFORMS:
        for query in queries:
            raw_items = _scrape_platform(platform, query, max_results=60)
            seen_on_platform: set[str] = set()
            for raw in raw_items:
                lst = _parse_vinted_listing(raw, platform)
                if (
                    lst
                    and lst.id not in seen_on_platform
                    and lst.price > 0
                    and _is_lego_set(lst.title, set_number, set_name)
                ):
                    seen_on_platform.add(lst.id)
                    all_listings.append(lst)
            time.sleep(1.0)

    # Classify into condition categories using our own classifier
    from src.analysis.condition_classifier import classify_condition

    categorized: dict[str, list[VintedListing]] = {
        "NIB": [],
        "CIB": [],
        "incomplete": [],
        "unknown": [],
    }
    for lst in all_listings:
        cat = classify_condition(lst.title, "")
        categorized[cat].append(lst)

    def _aggregate(listings: list[VintedListing], set_num: str, cat: str) -> SetPriceData:
        if not listings:
            return SetPriceData(
                set_number=set_num,
                condition_category=cat,
                listing_count=0,
                stale_count=0,
                avg_ask_price=None,
                stale_avg_price=None,
                realistic_sell_price=None,
                min_price=None,
                max_price=None,
                platforms=[],
            )
        prices = [lst.price for lst in listings]
        stale = [lst for lst in listings if lst.is_stale]
        stale_prices = [lst.price for lst in stale]
        avg = round(sum(prices) / len(prices), 2)
        stale_avg = round(sum(stale_prices) / len(stale_prices), 2) if stale_prices else None
        realistic = stale_avg if stale_avg else avg
        platforms = list({lst.platform for lst in listings})
        return SetPriceData(
            set_number=set_num,
            condition_category=cat,
            listing_count=len(listings),
            stale_count=len(stale),
            avg_ask_price=avg,
            stale_avg_price=stale_avg,
            realistic_sell_price=realistic,
            min_price=round(min(prices), 2),
            max_price=round(max(prices), 2),
            platforms=platforms,
        )

    result: dict[str, SetPriceData] = {}
    for cat, listings in categorized.items():
        result[cat] = _aggregate(listings, set_number, cat)

    # "all" = combined
    result["all"] = _aggregate(all_listings, set_number, "all")

    return result


def scrape_all_sets(lego_sets: list[dict]) -> dict[str, dict[str, SetPriceData]]:
    """
    Scrape Vinted for all LEGO sets.
    Returns dict: set_number -> {condition_category -> SetPriceData}
    Also saves to data/vinted_prices.json and updates history.
    """
    results: dict[str, dict[str, SetPriceData]] = {}

    for i, lego_set in enumerate(lego_sets, 1):
        set_number = lego_set["set_number"]
        name = lego_set["name"]
        print(f"[Vinted] [{i}/{len(lego_sets)}] Scraping set {set_number}: {name}")
        try:
            price_data = scrape_set_prices(set_number, name)
            results[set_number] = price_data
            total = price_data.get("all", None)
            count = total.listing_count if total else 0
            print(f"  → {count} listings found across platforms")
        except Exception as e:
            print(f"  → Error: {e}")
            results[set_number] = {}
        time.sleep(2.0)

    _save_prices(results)
    _update_history(results)
    return results


def _serialize_price_data(pd: SetPriceData) -> dict:
    return {
        "set_number": pd.set_number,
        "condition_category": pd.condition_category,
        "listing_count": pd.listing_count,
        "stale_count": pd.stale_count,
        "avg_ask_price": pd.avg_ask_price,
        "stale_avg_price": pd.stale_avg_price,
        "realistic_sell_price": pd.realistic_sell_price,
        "min_price": pd.min_price,
        "max_price": pd.max_price,
        "platforms": pd.platforms,
    }


def _save_prices(results: dict[str, dict[str, SetPriceData]]) -> None:
    VINTED_PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        "scraped_at": datetime.now().isoformat(),
        "sets": {
            set_number: {
                cat: _serialize_price_data(pd)
                for cat, pd in cat_data.items()
            }
            for set_number, cat_data in results.items()
        },
    }
    VINTED_PRICES_PATH.write_text(json.dumps(serializable, ensure_ascii=False, indent=2))


def _update_history(results: dict[str, dict[str, SetPriceData]]) -> None:
    """Append this week's data to vinted_price_history.json for chart rendering."""
    VINTED_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history: dict = {}
    if VINTED_HISTORY_PATH.exists():
        try:
            history = json.loads(VINTED_HISTORY_PATH.read_text())
        except Exception:
            history = {}

    week_key = datetime.now().strftime("%Y-W%V")  # ISO week, e.g. "2026-W12"

    for set_number, cat_data in results.items():
        if set_number not in history:
            history[set_number] = {}
        week_entry: dict = {}
        for cat, pd in cat_data.items():
            if pd.realistic_sell_price is not None:
                week_entry[cat] = {
                    "realistic_sell_price": pd.realistic_sell_price,
                    "avg_ask_price": pd.avg_ask_price,
                    "listing_count": pd.listing_count,
                }
        if week_entry:
            history[set_number][week_key] = week_entry

    # Keep max 52 weeks per set
    for set_number in history:
        weeks = sorted(history[set_number].keys())
        if len(weeks) > 52:
            for old_week in weeks[:-52]:
                del history[set_number][old_week]

    VINTED_HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2))


def load_prices() -> dict:
    """Load latest Vinted price data from disk."""
    if VINTED_PRICES_PATH.exists():
        try:
            return json.loads(VINTED_PRICES_PATH.read_text())
        except Exception:
            return {}
    return {}


def load_history() -> dict:
    """Load Vinted price history from disk."""
    if VINTED_HISTORY_PATH.exists():
        try:
            return json.loads(VINTED_HISTORY_PATH.read_text())
        except Exception:
            return {}
    return {}
