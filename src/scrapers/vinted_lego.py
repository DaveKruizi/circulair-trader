"""
Vinted LEGO scraper — price intelligence via lifecycle tracking.

Per LEGO set: scrapes Vinted NL using set-number-only search ("lego 42115").
- Set number must appear in listing title (confidence=0.95), else rejected
- Price outside [20%, 300%] of retail price → rejected + logged
- Incomplete condition → excluded from analysis + logged
- Tracks listing lifecycle in SQLite: detects disappeared listings (sold proxy)
"""

import os
import time
from datetime import datetime
from typing import Optional

try:
    from vinted_scraper import VintedScraper
    _VINTED_AVAILABLE = True
except ImportError:
    _VINTED_AVAILABLE = False

STALE_DAYS = 21
MIN_PRICE_RATIO = 0.20   # below 20% of retail = reject (scam / wrong product)
MAX_PRICE_RATIO = 3.00   # above 300% of retail = reject (wrong product)

VINTED_PLATFORMS = [
    ("https://www.vinted.nl", "vinted_nl"),
]

# Vinted native condition values that map to NIB / CIB / incomplete
_VINTED_NIB_RAW = {
    "1", "new_with_tags", "new with tags", "nieuw",
}
_VINTED_CIB_RAW = {
    "2", "new_without_tags", "new without tags", "als nieuw", "nieuw zonder prijskaartje",
    "3", "very_good", "very good", "heel goed",
    "4", "good", "goed",
    "5", "satisfactory", "veelgebruikt",
}
_VINTED_INCOMPLETE_RAW = {
    "6", "needs_repair", "moet gerepareerd worden",
}


def _classify_vinted_condition(title: str, condition_raw: str) -> str:
    """
    Classify Vinted listing condition using keyword matching first,
    then falling back to Vinted's own condition field.
    """
    from src.analysis.condition_classifier import classify_condition
    result = classify_condition(title, "")
    if result != "unknown":
        return result
    # Fallback: use Vinted native condition
    raw = (condition_raw or "").strip().lower()
    if raw in _VINTED_NIB_RAW:
        return "NIB"
    if raw in _VINTED_CIB_RAW:
        return "CIB"
    if raw in _VINTED_INCOMPLETE_RAW:
        return "incomplete"
    return "unknown"


def _get_session_cookie() -> Optional[dict]:
    token = os.getenv("VINTED_SESSION_COOKIE", "").strip()
    if not token:
        print("[Vinted] WARNING: VINTED_SESSION_COOKIE not set — library will try to auto-fetch cookie.")
        print("[Vinted]   If Vinted blocks the runner IP (e.g. GitHub Actions), all results will be 0.")
        print("[Vinted]   Fix: add VINTED_SESSION_COOKIE as a GitHub Actions secret.")
    return {"access_token_web": token} if token else None


def _scrape_platform(platform_url: str, query: str, max_results: int = 80) -> list:
    if not _VINTED_AVAILABLE:
        return []
    try:
        scraper = VintedScraper(platform_url, session_cookie=_get_session_cookie())
        params = {"search_text": query, "per_page": min(max_results, 96)}
        items = scraper.search(params) or []
        return list(items)[:max_results]
    except Exception as e:
        # Raise so the caller can count consecutive failures and abort early
        raise RuntimeError(f"Vinted request failed for '{query}' on {platform_url}: {e}") from e


def _parse_raw(raw, platform_code: str) -> Optional[dict]:
    try:
        listing_id = str(getattr(raw, "id", "") or "")
        title = str(getattr(raw, "title", "") or "")
        price_raw = getattr(raw, "price", None) or getattr(raw, "price_numeric", None)
        price = float(str(price_raw).replace(",", ".")) if price_raw else 0.0
        url = str(getattr(raw, "url", "") or "")

        photos = getattr(raw, "photos", None)
        image_url = ""
        if photos:
            first = photos[0] if photos else None
            if first:
                image_url = str(
                    getattr(first, "url", "")
                    or getattr(first, "full_size_url", "")
                    or ""
                )

        seller_obj = getattr(raw, "user", None) or getattr(raw, "seller", None)
        seller_id = str(getattr(seller_obj, "id", "") or "") if seller_obj else ""

        created_raw = getattr(raw, "created_at_ts", None) or getattr(raw, "created_at", None)
        days_old = 0
        if created_raw:
            try:
                if isinstance(created_raw, (int, float)):
                    dt = datetime.fromtimestamp(created_raw)
                else:
                    dt = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
                days_old = (datetime.now().date() - dt.date()).days
            except Exception:
                pass

        condition_obj = getattr(raw, "condition", None) or getattr(raw, "status", None)
        condition_raw = str(condition_obj) if condition_obj else ""

        return {
            "id": listing_id,
            "platform": platform_code,
            "title": title,
            "price": price,
            "condition_raw": condition_raw,
            "url": url,
            "image_url": image_url,
            "seller_id": seller_id,
            "days_old": days_old,
        }
    except Exception as e:
        print(f"[Vinted] Parse error: {e}")
        return None


def scrape_set(
    set_number: str,
    set_name: str,
    retail_price: Optional[float] = None,
) -> dict[str, list[dict]]:
    """
    Scrape Vinted for one LEGO set using 'lego {set_number}' query.

    Returns dict: platform_code -> list of valid listing dicts.
    Also updates SQLite lifecycle tracking and logs rejections.
    """
    from src.db import init_db, upsert_listing, mark_disappeared, log_rejection

    init_db()
    today = datetime.now().date().isoformat()

    min_price = (retail_price * MIN_PRICE_RATIO) if retail_price else 0.0
    max_price = (retail_price * MAX_PRICE_RATIO) if retail_price else float("inf")

    results: dict[str, list[dict]] = {}

    for platform_url, platform_code in VINTED_PLATFORMS:
        query = f"lego {set_number}"
        try:
            raw_items = _scrape_platform(platform_url, query, max_results=80)
        except RuntimeError as e:
            print(f"  [Vinted] SKIP {platform_code} for set {set_number}: {e}")
            results[platform_code] = []
            continue
        time.sleep(1.0)

        seen_ids: set[str] = set()
        valid_listings: list[dict] = []

        for raw in raw_items:
            parsed = _parse_raw(raw, platform_code)
            if not parsed or not parsed["id"] or parsed["id"] in seen_ids:
                continue

            lid = parsed["id"]
            title = parsed["title"]
            price = parsed["price"]

            # Must have set number in title (high-confidence match)
            if set_number not in title:
                log_rejection(
                    platform_code, set_number, lid, title, price,
                    "low_confidence", f"'{set_number}' not found in title"
                )
                continue

            if price <= 0:
                log_rejection(platform_code, set_number, lid, title, price,
                              "invalid_price", "price is zero or negative")
                continue

            if retail_price and price < min_price:
                log_rejection(
                    platform_code, set_number, lid, title, price,
                    "price_too_low",
                    f"€{price:.0f} < {MIN_PRICE_RATIO*100:.0f}% of retail €{retail_price:.0f}",
                    image_url=parsed["image_url"],
                    url=parsed["url"],
                )
                continue

            if retail_price and price > max_price:
                log_rejection(
                    platform_code, set_number, lid, title, price,
                    "price_too_high",
                    f"€{price:.0f} > {MAX_PRICE_RATIO*100:.0f}% of retail €{retail_price:.0f}"
                )
                continue

            condition = _classify_vinted_condition(title, parsed["condition_raw"])
            if condition == "incomplete":
                log_rejection(
                    platform_code, set_number, lid, title, price,
                    "incomplete", "condition classified as incomplete (cat C)"
                )
                continue

            seen_ids.add(lid)
            upsert_listing(
                listing_id=lid,
                platform=platform_code,
                set_number=set_number,
                title=title,
                price=price,
                condition_category=condition,
                condition_raw=parsed["condition_raw"],
                url=parsed["url"],
                image_url=parsed["image_url"],
                seller_id=parsed["seller_id"],
                today=today,
                match_confidence=0.95,
            )

            parsed["condition_category"] = condition
            parsed["is_stale"] = parsed["days_old"] >= STALE_DAYS
            valid_listings.append(parsed)

        if seen_ids:
            disappeared = mark_disappeared(platform_code, set_number, seen_ids, today)
            if disappeared:
                print(f"  [Lifecycle] {disappeared} listings gone from {platform_code} → sold proxy")
        else:
            print(f"  [Lifecycle] SKIP mark_disappeared for {platform_code} set {set_number}: 0 results (auth issue?)")

        results[platform_code] = valid_listings

    return results


def scrape_all_sets(lego_sets: list[dict]) -> dict[str, dict[str, list[dict]]]:
    """
    Scrape Vinted for all LEGO sets.
    Returns dict: set_number -> {platform_code -> [listing dicts]}

    Raises RuntimeError if every single set returned 0 results — this signals a
    connectivity/auth problem (blocked IP, expired cookie) rather than genuine
    "no listings found".
    """
    results: dict[str, dict[str, list[dict]]] = {}
    sets_with_results = 0

    for i, lego_set in enumerate(lego_sets, 1):
        set_number = lego_set["set_number"]
        name = lego_set["name"]
        retail_price = lego_set.get("retail_price")
        print(f"[Vinted] [{i}/{len(lego_sets)}] Scraping set {set_number}: {name}")
        try:
            platform_data = scrape_set(set_number, name, retail_price)
            results[set_number] = platform_data
            total = sum(len(v) for v in platform_data.values())
            print(f"  → {total} valid listings found")
            if total > 0:
                sets_with_results += 1
        except Exception as e:
            print(f"  → Error: {e}")
            results[set_number] = {}
        time.sleep(2.0)

    if lego_sets and sets_with_results == 0:
        raise RuntimeError(
            "[Vinted] FATAL: 0 results across all sets — Vinted is likely blocking this IP "
            "or the session cookie is invalid/missing.\n"
            "Fix: set VINTED_SESSION_COOKIE as a GitHub Actions secret.\n"
            "How to get it: log in to vinted.nl → DevTools → Application → "
            "Cookies → copy the value of 'access_token_web'."
        )

    return results
