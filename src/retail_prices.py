"""
Haalt retailprijzen op van lego.com/nl-nl en schrijft ze terug naar
data/lego_sets.json.

LEGO.com behoudt de laatste verkoopprijs in de HTML zelfs voor retired sets
(element: data-test="product-price-display-price").

Wordt wekelijks aangeroepen vanuit de dagelijkse orchestrator.
"""

import json
import re
import time
import unicodedata
from datetime import date
from pathlib import Path

import requests

LEGO_SETS_PATH = Path("data/lego_sets.json")
NL_BASE = "https://www.lego.com/nl-nl/product"
DELAY_SECONDS = 1.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def to_slug(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def fetch_price(set_number: str, name: str) -> float | None:
    slug = to_slug(name)
    url = f"{NL_BASE}/{slug}-{set_number}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    except requests.RequestException as e:
        print(f"    ✗ Verbindingsfout: {e}")
        return None

    if resp.status_code == 404:
        print(f"    ✗ 404 — niet gevonden ({url})")
        return None

    if not resp.ok:
        print(f"    ✗ HTTP {resp.status_code} voor {url}")
        return None

    html = resp.text

    match = re.search(
        r'data-test=["\']product-price-display-price["\'][^>]*>\s*\u20ac\s*([\d.,]+)',
        html,
    )
    if match:
        try:
            return float(match.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            pass

    match = re.search(r'"price"\s*:\s*"([\d.]+)"', html)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    match = re.search(r'[Pp]rice[^€]{0,60}\u20ac\s*([\d]+[,.][\d]{2})', html)
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            pass

    print(f"    ? Prijs niet gevonden in HTML ({url})")
    return None


def run_update(dry_run: bool = False, filter_sets: list[str] | None = None) -> dict:
    """
    Haalt retailprijzen op voor alle (of gefilterde) sets en slaat ze op.

    Returns dict met keys: updated, unchanged, skipped (lijsten met set_numbers).
    """
    data = json.loads(LEGO_SETS_PATH.read_text(encoding="utf-8"))
    sets = data["sets"]

    if filter_sets:
        sets = [s for s in sets if s["set_number"] in filter_sets]

    result = {"updated": [], "unchanged": [], "skipped": []}

    for lego_set in sets:
        set_number = lego_set["set_number"]
        name = lego_set["name"]
        current = lego_set.get("retail_price")

        print(f"[{set_number}] {name}  (huidig: {'€' + str(current) if current else '—'})")

        new_price = fetch_price(set_number, name)
        time.sleep(DELAY_SECONDS)

        if new_price is None:
            result["skipped"].append(set_number)
            continue

        if new_price != current:
            arrow = "↑" if (new_price or 0) > (current or 0) else "↓"
            print(f"    {arrow} €{current} → €{new_price}")
            result["updated"].append((set_number, name, current, new_price))
            if not dry_run:
                lego_set["retail_price"] = new_price
        else:
            print(f"    = €{new_price} (ongewijzigd)")
            result["unchanged"].append(set_number)

    if not dry_run and result["updated"]:
        data["last_price_update"] = date.today().isoformat()
        LEGO_SETS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n✓ lego_sets.json bijgewerkt ({len(result['updated'])} prijzen gewijzigd)")

    return result


def should_run_today(data: dict) -> bool:
    """True als er geen prijsupdate de afgelopen 7 dagen is geweest."""
    last = data.get("last_price_update")
    if not last:
        return True
    delta = (date.today() - date.fromisoformat(last)).days
    return delta >= 7
