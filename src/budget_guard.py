"""
Budget guard — stopt de tool als de API-kosten te hoog worden.

Houdt bij hoeveel tokens gebruikt zijn en berekent de kosten.
Als het budget overschreden wordt:
  1. Schrijft een waarschuwing naar output/BUDGET_OVERSCHREDEN.txt
  2. Gooit een BudgetExceededError zodat de tool stopt
  3. Toont een duidelijke melding in de terminal

Prijzen Claude Opus 4.6:
  Input:  $5.00 per 1M tokens
  Output: $25.00 per 1M tokens
"""

import json
from datetime import datetime
from pathlib import Path

BUDGET_EUR = 10.0
BUDGET_USD = BUDGET_EUR / 0.92  # ~$10.87

# Prijzen per token (Claude Opus 4.6)
PRICE_INPUT_PER_TOKEN = 5.00 / 1_000_000    # $0.000005
PRICE_OUTPUT_PER_TOKEN = 25.00 / 1_000_000  # $0.000025

USAGE_FILE = Path("data/api_usage.json")
OUTPUT_DIR = "output"


class BudgetExceededError(Exception):
    pass


def _load_usage() -> dict:
    """Laad huidige maandelijkse verbruiksdata."""
    if not USAGE_FILE.exists():
        return {"month": datetime.now().strftime("%Y-%m"), "input_tokens": 0, "output_tokens": 0}
    try:
        data = json.loads(USAGE_FILE.read_text())
        # Reset als het een nieuwe maand is
        if data.get("month") != datetime.now().strftime("%Y-%m"):
            return {"month": datetime.now().strftime("%Y-%m"), "input_tokens": 0, "output_tokens": 0}
        return data
    except Exception:
        return {"month": datetime.now().strftime("%Y-%m"), "input_tokens": 0, "output_tokens": 0}


def _save_usage(data: dict):
    """Sla verbruiksdata op."""
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, indent=2))


def calculate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Bereken kosten in USD."""
    return (
        input_tokens * PRICE_INPUT_PER_TOKEN
        + output_tokens * PRICE_OUTPUT_PER_TOKEN
    )


def register_usage(input_tokens: int, output_tokens: int):
    """
    Registreer API gebruik en controleer of budget overschreden is.

    Gooit BudgetExceededError als de limiet bereikt is.
    """
    data = _load_usage()
    data["input_tokens"] += input_tokens
    data["output_tokens"] += output_tokens
    _save_usage(data)

    total_cost_usd = calculate_cost_usd(data["input_tokens"], data["output_tokens"])
    total_cost_eur = total_cost_usd * 0.92

    if total_cost_eur >= BUDGET_EUR:
        _trigger_budget_alert(total_cost_eur)
        raise BudgetExceededError(
            f"Budget overschreden: €{total_cost_eur:.2f} van €{BUDGET_EUR:.2f} gebruikt deze maand."
        )

    # Waarschuwing bij 80%
    if total_cost_eur >= BUDGET_EUR * 0.8:
        print(f"\n⚠️  WAARSCHUWING: API kosten zijn €{total_cost_eur:.2f} van €{BUDGET_EUR:.2f} (80% van budget)")


def get_current_cost() -> dict:
    """Geef huidige kostendata terug."""
    data = _load_usage()
    cost_usd = calculate_cost_usd(data["input_tokens"], data["output_tokens"])
    cost_eur = cost_usd * 0.92
    return {
        "month": data["month"],
        "input_tokens": data["input_tokens"],
        "output_tokens": data["output_tokens"],
        "cost_usd": round(cost_usd, 4),
        "cost_eur": round(cost_eur, 4),
        "total_cost_eur": round(cost_eur, 2),   # used by dashboard generator
        "monthly_budget_eur": BUDGET_EUR,
        "budget_eur": BUDGET_EUR,
        "remaining_eur": round(max(0, BUDGET_EUR - cost_eur), 4),
        "pct_used": round(cost_eur / BUDGET_EUR * 100, 1),
    }


def _trigger_budget_alert(cost_eur: float):
    """Schrijf een duidelijke waarschuwing naar het output-dashboard."""
    alert_file = Path(OUTPUT_DIR) / "BUDGET_OVERSCHREDEN.txt"
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    message = f"""
╔══════════════════════════════════════════════════════╗
║         ⛔  BUDGET OVERSCHREDEN — TOOL GESTOPT       ║
╠══════════════════════════════════════════════════════╣
║  Datum:    {datetime.now().strftime('%d %B %Y, %H:%M')}
║  Kosten:   €{cost_eur:.2f} van €{BUDGET_EUR:.2f} budget
║  Maand:    {datetime.now().strftime('%B %Y')}
╠══════════════════════════════════════════════════════╣
║  Wat te doen:                                        ║
║  1. Controleer je verbruik op console.anthropic.com  ║
║  2. Verwijder dit bestand om de tool te hervatten    ║
║     (src/budget_guard.py reset automatisch per maand)║
╚══════════════════════════════════════════════════════╝
"""
    alert_file.write_text(message)

    print(message)
    print(f"⛔ Waarschuwingsbestand aangemaakt: {alert_file}")
