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

    if action == "verwijderen":
        delete_ids_str = os.environ.get("DELETE_IDS", "").strip()
        if not delete_ids_str:
            print("[Portfolio] FOUT: DELETE_IDS is verplicht bij verwijderen (bijv. '1,2,3')")
            sys.exit(1)
        try:
            ids = [int(x.strip()) for x in delete_ids_str.split(",") if x.strip()]
        except ValueError as e:
            print(f"[Portfolio] FOUT: Ongeldige ID — {e}")
            sys.exit(1)
        count = db.delete_portfolio_positions(ids)
        print(f"[Portfolio] ✓ {count} positie(s) verwijderd (IDs: {ids})")
        return

    if action == "splitsen":
        position_id_str = os.environ.get("POSITION_ID", "").strip()
        if not position_id_str:
            print("[Portfolio] FOUT: POSITION_ID is verplicht bij splitsen")
            sys.exit(1)
        try:
            position_id = int(position_id_str)
        except ValueError as e:
            print(f"[Portfolio] FOUT: Ongeldige ID — {e}")
            sys.exit(1)
        pos = db.get_portfolio_position(position_id)
        if not pos:
            print(f"[Portfolio] FOUT: Positie {position_id} niet gevonden")
            sys.exit(1)
        qty = pos["quantity"]
        if qty < 2:
            print(f"[Portfolio] FOUT: Positie {position_id} heeft slechts {qty} stuk(s) — splitsen niet mogelijk")
            sys.exit(1)
        # Verwijder originele positie en maak qty losse posities aan
        db.delete_portfolio_positions([position_id])
        new_ids = []
        for _ in range(qty):
            new_id = db.add_portfolio_position(
                set_number=pos["set_number"],
                condition=pos["condition"],
                quantity=1,
                purchase_price=pos["purchase_price"],
                purchase_date=pos["purchase_date"],
                notes=pos.get("notes") or "",
            )
            new_ids.append(new_id)
        print(f"[Portfolio] ✓ Positie {position_id} ({qty}×) gesplitst in {qty} losse posities (IDs: {new_ids})")
        return

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
