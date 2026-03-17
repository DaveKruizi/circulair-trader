"""
Dashboard generator for LEGO Circulair Trader.

Renders the Jinja2 HTML template with LEGO set data, deals, and Vinted prices.
Writes output to the output/ directory for GitHub Pages deployment.
"""

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent / "templates"
OUTPUT_DIR = Path("output")
GITHUB_REPO = "DaveKruizi/circulair-trader"
API_COST_PATH = Path("data/api_usage.json")


def _load_api_cost() -> dict:
    """Load current month API cost from api_usage.json."""
    if API_COST_PATH.exists():
        try:
            return json.loads(API_COST_PATH.read_text())
        except Exception:
            pass
    return {"total_cost_eur": 0.0, "monthly_budget_eur": 10.0, "month": ""}


def generate_dashboard(
    sets: list[dict],
    scraped_at: str,
    total_deals: int,
    new_today: int,
    price_drops: int,
    vinted_prices_date: str = "",
) -> str:
    """
    Render the LEGO dashboard HTML and write to output/index.html.

    Args:
        sets: List of enriched lego_set dicts, each with 'deals' list attached.
        scraped_at: ISO timestamp of last Marktplaats scrape.
        total_deals: Total qualifying deals across all sets.
        new_today: Number of deals seen for the first time today.
        price_drops: Number of deals where price dropped since last scrape.
        vinted_prices_date: ISO timestamp of last Vinted scrape.

    Returns:
        Path to generated HTML file.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    from urllib.parse import quote_plus
    env.filters["urlencode"] = quote_plus

    template = env.get_template("dashboard.html")

    now = datetime.now()

    # Gather all themes for filter
    themes = sorted({s.get("theme", "Overig") for s in sets})

    # API cost data
    api_cost = _load_api_cost()
    cost_eur = float(api_cost.get("total_cost_eur", 0.0))
    budget_eur = float(api_cost.get("monthly_budget_eur", 10.0))
    cost_pct = min(round((cost_eur / budget_eur) * 100, 1), 100.0) if budget_eur > 0 else 0.0

    # Stats
    sets_with_deals = sum(1 for s in sets if s.get("deal_count", 0) > 0)
    sets_with_vinted = sum(1 for s in sets if s.get("vinted_total_count", 0) > 0)

    html = template.render(
        sets=sets,
        themes=themes,
        scraped_at=_format_dt(scraped_at),
        vinted_prices_date=_format_dt(vinted_prices_date),
        generated_at=now.strftime("%d %b %Y, %H:%M"),
        total_deals=total_deals,
        new_today=new_today,
        price_drops=price_drops,
        sets_with_deals=sets_with_deals,
        total_sets=len(sets),
        sets_with_vinted=sets_with_vinted,
        cost_eur=round(cost_eur, 2),
        budget_eur=budget_eur,
        cost_pct=cost_pct,
        github_repo=GITHUB_REPO,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / "index.html"
    out_file.write_text(html, encoding="utf-8")

    archive_file = OUTPUT_DIR / f"dashboard_{now.strftime('%Y-%m-%d')}.html"
    archive_file.write_text(html, encoding="utf-8")

    nojekyll = OUTPUT_DIR / ".nojekyll"
    if not nojekyll.exists():
        nojekyll.touch()

    print(f"[Dashboard] Generated: {out_file}")
    return str(out_file)


def _format_dt(iso_str: str) -> str:
    """Format ISO timestamp to human-readable Dutch date/time."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.split("T")[0] if "T" in iso_str else iso_str)
        return dt.strftime("%d %b %Y")
    except Exception:
        return iso_str[:10] if iso_str else "—"
