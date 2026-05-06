"""
BrickEconomy.com scraper — monthly market value cache.

Scrapes NIB (New/Sealed) and Used market values per LEGO set.
Results are cached in SQLite for 30 days to stay within polite scraping limits.

URL format: https://www.brickeconomy.com/set/{set_number}-1/

Currency handling:
- BrickEconomy shows EUR (€) for European IPs, USD ($) for US IPs.
- If USD is detected (e.g. on GitHub Actions), values are converted to EUR
  using the rate in BRICKECONOMY_EUR_USD_RATE env var (default: 0.92).
"""

import os
import re
import time
from typing import Optional

import httpx
from bs4 import BeautifulSoup

SCRAPE_INTERVAL_DAYS = 30

# USD→EUR conversion fallback (update or override via env var)
_EUR_USD_RATE = float(os.getenv("BRICKECONOMY_EUR_USD_RATE", "0.92"))

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _parse_amount(amount_str: str) -> Optional[float]:
    """Parse '240.42' or '1,240.42' to float."""
    cleaned = re.sub(r",(\d{3})", r"\1", amount_str.strip())
    try:
        return float(cleaned)
    except ValueError:
        m = re.search(r"[\d.]+", cleaned)
        return float(m.group()) if m else None


def _parse_html(html: str) -> Optional[dict]:
    """
    Extract NIB and Used market values from a BrickEconomy set page.

    Returns {"nib": float|None, "used": float|None, "currency": str}
    or None if no pricing data could be found.

    Strategy: text-based regex scan of the full page text — robust against
    layout changes since BrickEconomy keeps the same section labels.
    """
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    nib_value: Optional[float] = None
    used_value: Optional[float] = None
    currency = "EUR"

    # Pattern: "New/Sealed" header → ... → "Value" → currency symbol + amount
    # The [^€$£\d]*? skips tooltip text like "(?) " without consuming price chars.
    nib_m = re.search(
        r"New\s*/?\s*Sealed[^€$£\d]{0,80}?Value[^€$£\d]{0,30}?([€$£])\s*([\d,]+\.?\d*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if nib_m:
        currency = "EUR" if nib_m.group(1) == "€" else "USD"
        nib_value = _parse_amount(nib_m.group(2))

    # Pattern: "Used" header → ... → "Value" → currency symbol + amount
    # Anchored to appear after the NIB section to avoid false matches.
    search_start = nib_m.end() if nib_m else 0
    used_m = re.search(
        r"Used[^€$£\d]{0,80}?Value[^€$£\d]{0,30}?([€$£])\s*([\d,]+\.?\d*)",
        text[search_start:],
        re.IGNORECASE | re.DOTALL,
    )
    if used_m:
        if nib_m is None:
            currency = "EUR" if used_m.group(1) == "€" else "USD"
        used_value = _parse_amount(used_m.group(2))

    if nib_value is None and used_value is None:
        return None

    # Convert USD → EUR if BrickEconomy returned dollar amounts (US-based runner)
    if currency == "USD":
        if nib_value is not None:
            nib_value = round(nib_value * _EUR_USD_RATE, 2)
        if used_value is not None:
            used_value = round(used_value * _EUR_USD_RATE, 2)
        currency = "EUR"

    return {"nib": nib_value, "used": used_value, "currency": currency}


def _fetch(set_number: str) -> Optional[dict]:
    """Fetch BrickEconomy page and return parsed pricing dict, or None on failure."""
    url = f"https://www.brickeconomy.com/set/{set_number}-1/"
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=15, follow_redirects=True)
    except Exception as e:
        print(f"  [BrickEconomy] Network error for {set_number}: {e}")
        return None

    if resp.status_code == 404:
        print(f"  [BrickEconomy] Set {set_number} not found on BrickEconomy")
        return None
    if resp.status_code != 200:
        print(f"  [BrickEconomy] HTTP {resp.status_code} for {set_number}")
        return None

    result = _parse_html(resp.text)
    if result is None:
        print(f"  [BrickEconomy] Could not parse pricing for {set_number} (layout changed?)")
    return result


def scrape_set(set_number: str, force: bool = False) -> Optional[dict]:
    """
    Return BrickEconomy market values for one set.
    Uses DB cache; only scrapes if cache is older than SCRAPE_INTERVAL_DAYS.
    Returns {"nib": float|None, "used": float|None} or None if unavailable.
    """
    from src.db import get_brickeconomy_cache, upsert_brickeconomy_cache, is_brickeconomy_fresh

    if not force and is_brickeconomy_fresh(set_number, max_age_days=SCRAPE_INTERVAL_DAYS):
        cached = get_brickeconomy_cache(set_number)
        if cached:
            return cached

    result = _fetch(set_number)
    if result:
        upsert_brickeconomy_cache(
            set_number=set_number,
            nib_value=result.get("nib"),
            used_value=result.get("used"),
            currency=result.get("currency", "EUR"),
        )
    return result


def scrape_all_sets(lego_sets: list[dict], force: bool = False) -> dict[str, dict]:
    """
    Refresh BrickEconomy cache for all sets that are stale (> 30 days).
    Fresh sets are loaded from DB cache without an HTTP request.
    Returns dict: set_number -> {"nib": float|None, "used": float|None}
    """
    from src.db import init_db, get_brickeconomy_cache, is_brickeconomy_fresh

    init_db()
    results: dict[str, dict] = {}
    stale = [s for s in lego_sets if force or not is_brickeconomy_fresh(s["set_number"], SCRAPE_INTERVAL_DAYS)]
    fresh = [s for s in lego_sets if s not in stale]

    # Load fresh entries from cache (no HTTP)
    for lego_set in fresh:
        cached = get_brickeconomy_cache(lego_set["set_number"])
        if cached:
            results[lego_set["set_number"]] = cached

    if not stale:
        print(f"[BrickEconomy] All {len(fresh)} sets have fresh cache — skipping scrape")
        return results

    print(f"[BrickEconomy] Scraping {len(stale)} stale sets ({len(fresh)} already cached)")
    for i, lego_set in enumerate(stale, 1):
        set_number = lego_set["set_number"]
        name = lego_set["name"]
        print(f"[BrickEconomy] [{i}/{len(stale)}] {set_number}: {name}")
        result = _fetch(set_number)
        if result:
            from src.db import upsert_brickeconomy_cache
            upsert_brickeconomy_cache(
                set_number=set_number,
                nib_value=result.get("nib"),
                used_value=result.get("used"),
                currency=result.get("currency", "EUR"),
            )
            results[set_number] = result
            nib_str = f"€{result['nib']:.2f}" if result.get("nib") else "—"
            used_str = f"€{result['used']:.2f}" if result.get("used") else "—"
            print(f"  → NIB: {nib_str}, Used: {used_str}")
        else:
            print(f"  → No data")
        if i < len(stale):
            time.sleep(2.5)  # polite delay between requests

    return results
