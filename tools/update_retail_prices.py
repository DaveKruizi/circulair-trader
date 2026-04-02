#!/usr/bin/env python3
"""
CLI-wrapper voor src/retail_prices.py — voor handmatig gebruik.

Gebruik:
    python tools/update_retail_prices.py            # update lego_sets.json
    python tools/update_retail_prices.py --dry-run  # alleen tonen, niet opslaan
    python tools/update_retail_prices.py 10242      # specifieke set bijwerken
"""

import sys
from pathlib import Path

# Zorg dat de project-root op het pad staat zodat 'src' importeerbaar is
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retail_prices import run_update


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    filter_sets = [a for a in sys.argv[1:] if not a.startswith("-")] or None

    if dry_run:
        print("⚠  DRY-RUN — geen wijzigingen worden opgeslagen\n")
    if filter_sets:
        print(f"Filter: {filter_sets}\n")

    result = run_update(dry_run=dry_run, filter_sets=filter_sets)

    print(f"\n{'='*50}")
    print(f"Bijgewerkt  : {len(result['updated'])}")
    print(f"Ongewijzigd : {len(result['unchanged'])}")
    print(f"Overgeslagen: {len(result['skipped'])}")

    if result["updated"]:
        print("\nWijzigingen:")
        for sn, nm, old, new in result["updated"]:
            arrow = "↑" if (new or 0) > (old or 0) else "↓"
            print(f"  {arrow} [{sn}] {nm}: €{old} → €{new}")

    if result["skipped"]:
        print("\nNiet gevonden op LEGO.com (bestaande prijs bewaard):")
        for s in result["skipped"]:
            print(f"  - {s}")

    if dry_run:
        print("\n(dry-run — geen wijzigingen opgeslagen)")


if __name__ == "__main__":
    main()
