"""
Portfolio beheer CLI — aangeroepen door de portfolio-manage GitHub Actions workflow.
Leest actieparameters uit omgevingsvariabelen.
"""

import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from src import db


def main() -> None:
    db.init_db()

    action = os.environ.get("ACTION", "").strip().lower()
    set_number = os.environ.get("SET_NUMBER", "").strip()
    condition = os.environ.get("CONDITION", "").strip().upper()

    if not set_number:
        print("[Portfolio] FOUT: SET_NUMBER is verplicht")
        sys.exit(1)

    if action == "kopen":
        purchase_price_str = os.environ.get("PURCHASE_PRICE", "").strip()
        purchase_date = os.environ.get("PURCHASE_DATE", "").strip()
        quantity_str = os.environ.get("QUANTITY", "1").strip() or "1"
        notes = os.environ.get("NOTES", "").strip()

        if not purchase_price_str or not purchase_date:
            print("[Portfolio] FOUT: PURCHASE_PRICE en PURCHASE_DATE zijn verplicht bij kopen")
            sys.exit(1)

        try:
            purchase_price = float(purchase_price_str)
            quantity = int(quantity_str)
        except ValueError as e:
            print(f"[Portfolio] FOUT: Ongeldige waarde — {e}")
            sys.exit(1)

        new_id = db.add_portfolio_position(
            set_number=set_number,
            condition=condition,
            quantity=quantity,
            purchase_price=purchase_price,
            purchase_date=purchase_date,
            notes=notes,
        )
        print(
            f"[Portfolio] ✓ Positie toegevoegd (id={new_id}): "
            f"{quantity}× set {set_number} {condition} @ €{purchase_price:.2f} op {purchase_date}"
        )

    elif action == "verkopen":
        sold_price_str = os.environ.get("SOLD_PRICE", "").strip()
        sold_date = os.environ.get("SOLD_DATE", "").strip()
        position_id_str = os.environ.get("POSITION_ID", "").strip()

        if not sold_price_str or not sold_date or not position_id_str:
            print("[Portfolio] FOUT: SOLD_PRICE, SOLD_DATE en POSITION_ID zijn verplicht bij verkopen")
            sys.exit(1)

        try:
            sold_price = float(sold_price_str)
            position_id = int(position_id_str)
        except ValueError as e:
            print(f"[Portfolio] FOUT: Ongeldige waarde — {e}")
            sys.exit(1)

        ok = db.sell_portfolio_position(position_id, sold_price, sold_date)
        if ok:
            print(
                f"[Portfolio] ✓ Positie {position_id} verkocht: "
                f"€{sold_price:.2f} op {sold_date}"
            )
        else:
            print(f"[Portfolio] FOUT: Positie {position_id} niet gevonden of al verkocht")
            sys.exit(1)

    else:
        print(f"[Portfolio] FOUT: Onbekende actie '{action}'. Gebruik 'kopen' of 'verkopen'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
