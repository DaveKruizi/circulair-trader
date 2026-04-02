#!/usr/bin/env python3
"""
Haal de laatste retailprijzen op van lego.com/nl-nl voor alle sets in
data/lego_sets.json en sla ze op.

LEGO.com behoudt de laatste verkoopprijs in de HTML zelfs voor uitverkochte
/retired sets (element: data-test="product-price-display-price").

URL-formaat: https://www.lego.com/nl-nl/product/{slug}-{setnummer}
  bijv. https://www.lego.com/nl-nl/product/mini-cooper-10242

Gebruik:
    python tools/update_retail_prices.py            # update lego_sets.json
    python tools/update_retail_prices.py --dry-run  # alleen tonen, niet opslaan
    python tools/update_retail_prices.py 10242      # specifieke set bijwerken

Bij een 404 of ontbrekende prijs wordt de bestaande prijs bewaard.
"""

import json
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

import requests

LEGO_SETS_PATH = Path("data/lego_sets.json")
NL_BASE = "https://www.lego.com/nl-nl/product"
DELAY_SECONDS = 1.5  # respectvolle pauze tussen verzoeken

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def to_slug(name: str) -> str:
    """
    Converteer een setnaam naar LEGO.com URL-slug.

    Stappen:
    1. Unicode normalisatie (accenten verwijderen: é→e, ü→u, etc.)
    2. Lowercase
    3. Elk non-alfanumeriek karakter → koppelteken
    4. Overbodige koppeltekens aan begin/eind verwijderen

    Voorbeelden:
      'MINI Cooper'                → 'mini-cooper'
      'Lamborghini Huracán Tecnica'→ 'lamborghini-huracan-tecnica'
      'McLaren MP4/4 & Ayrton Senna'→ 'mclaren-mp4-4-ayrton-senna'
    """
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def fetch_price(set_number: str, name: str) -> float | None:
    """
    Haal retailprijs op van lego.com/nl-nl/product/{slug}-{set_number}.
    Geeft float terug of None als de prijs niet gevonden is.
    """
    slug = to_slug(name)
    url = f"{NL_BASE}/{slug}-{set_number}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    except requests.RequestException as e:
        print(f"    ✗ Verbindingsfout: {e}")
        return None

    if resp.status_code == 404:
        print(f"    ✗ 404 — set niet gevonden op LEGO.com (URL: {url})")
        return None

    if not resp.ok:
        print(f"    ✗ HTTP {resp.status_code} voor {url}")
        return None

    html = resp.text

    # Primaire patroon: data-test="product-price-display-price">€99,99
    match = re.search(
        r'data-test=["\']product-price-display-price["\'][^>]*>\s*\u20ac\s*([\d.,]+)',
        html,
    )
    if match:
        price_str = match.group(1).replace(".", "").replace(",", ".")
        try:
            return float(price_str)
        except ValueError:
            pass

    # Fallback: zoek naar prijs in JSON-LD structured data ("price": "99.99")
    match = re.search(r'"price"\s*:\s*"([\d.]+)"', html)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    # Fallback 2: zoek naar €XX,XX patroon in de buurt van 'price'
    match = re.search(r'[Pp]rice[^€]{0,60}\u20ac\s*([\d]+[,.][\d]{2})', html)
    if match:
        price_str = match.group(1).replace(",", ".")
        try:
            return float(price_str)
        except ValueError:
            pass

    print(f"    ? Prijs niet gevonden in HTML (URL: {url})")
    return None


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    # Optionele filter op specifieke setnummers
    filter_sets = [a for a in sys.argv[1:] if not a.startswith("-")]

    data = json.loads(LEGO_SETS_PATH.read_text(encoding="utf-8"))
    sets = data["sets"]

    if filter_sets:
        sets = [s for s in sets if s["set_number"] in filter_sets]
        print(f"Filter: {len(sets)} set(s) — {', '.join(filter_sets)}\n")
    else:
        print(f"Bijwerken van {len(sets)} sets via lego.com/nl-nl ...\n")

    if dry_run:
        print("⚠  DRY-RUN — geen wijzigingen worden opgeslagen\n")

    updated = []
    unchanged = []
    skipped = []

    for lego_set in sets:
        set_number = lego_set["set_number"]
        name = lego_set["name"]
        current = lego_set.get("retail_price")

        print(f"[{set_number}] {name}  (huidig: {'€' + str(current) if current else '—'})")

        new_price = fetch_price(set_number, name)
        time.sleep(DELAY_SECONDS)

        if new_price is None:
            skipped.append(f"{set_number} — {name}")
            continue

        if new_price != current:
            print(f"    ✓ €{current} → €{new_price}")
            updated.append((set_number, name, current, new_price))
            if not dry_run:
                lego_set["retail_price"] = new_price
        else:
            print(f"    = €{new_price} (ongewijzigd)")
            unchanged.append(set_number)

    # Schrijf resultaat terug
    if not dry_run and updated:
        data["last_updated"] = date.today().isoformat()
        LEGO_SETS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n✓ lego_sets.json opgeslagen ({len(updated)} prijzen bijgewerkt)")

    # Samenvatting
    print(f"\n{'='*50}")
    print(f"Bijgewerkt    : {len(updated)}")
    print(f"Ongewijzigd   : {len(unchanged)}")
    print(f"Overgeslagen  : {len(skipped)}")

    if updated:
        print("\nWijzigingen:")
        for sn, nm, old, new in updated:
            arrow = "↑" if (new or 0) > (old or 0) else "↓"
            print(f"  {arrow} [{sn}] {nm}: €{old} → €{new}")

    if skipped:
        print("\nNiet gevonden op LEGO.com (bestaande prijs bewaard):")
        for s in skipped:
            print(f"  - {s}")

    if dry_run:
        print("\n(dry-run — geen wijzigingen opgeslagen)")


if __name__ == "__main__":
    main()
