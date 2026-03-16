"""
Dashboard generator.

Renders the Jinja2 HTML template with opportunity and trend data.
Writes output to the configured OUTPUT_DIR.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.config import OUTPUT_DIR, GITHUB_REPO
from src.budget_guard import get_current_cost


TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_dashboard(
    opportunities: list,
    trends: list,
    sources_scanned: list[str],
    trend_history: dict = None,
) -> str:
    """
    Render the dashboard HTML and write to output directory.

    Args:
        opportunities: List of Opportunity objects.
        trends: List of VintedTrend objects.
        sources_scanned: List of platform names that were scraped.
        trend_history: Dict of date -> {term -> data} for trend charts.

    Returns:
        Path to the generated HTML file.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    # Add urlencode filter
    from urllib.parse import quote_plus
    env.filters["urlencode"] = quote_plus

    template = env.get_template("dashboard.html")

    now = datetime.now()
    next_run = now + timedelta(days=1)
    next_run = next_run.replace(hour=7, minute=0, second=0)

    viable_opps = [o for o in opportunities if o.is_viable]
    profits = [o.net_profit for o in viable_opps]

    new_deals = [o for o in viable_opps if o.is_new]
    returning_deals = [o for o in viable_opps if not o.is_new]

    stats = {
        "total_opportunities": len(viable_opps),
        "best_profit": f"{max(profits):.2f}" if profits else "0.00",
        "avg_profit": f"{sum(profits) / len(profits):.2f}" if profits else "0.00",
        "low_risk_count": sum(1 for o in viable_opps if o.risk_score >= 7.5),
        "sources_scanned": len(sources_scanned),
        "new_deals_count": len(new_deals),
        "returning_deals_count": len(returning_deals),
    }

    # Prepare trend chart data (last 28 days)
    trend_chart_data = _prepare_trend_chart(trend_history) if trend_history else {}

    html = template.render(
        opportunities=viable_opps[:20],
        new_deals=new_deals[:20],
        returning_deals=returning_deals[:20],
        trends=trends,
        stats=stats,
        generated_at=now.strftime("%d %b %Y, %H:%M"),
        next_update=next_run.strftime("%d %b %Y, %H:%M"),
        date_label=now.strftime("%d %B %Y"),
        api_cost=get_current_cost(),
        trend_chart_data=json.dumps(trend_chart_data),
        github_repo=GITHUB_REPO,
    )

    # Write output
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)
    out_file = output_path / "index.html"
    out_file.write_text(html, encoding="utf-8")

    # Also write a dated archive copy
    archive_file = output_path / f"dashboard_{now.strftime('%Y-%m-%d')}.html"
    archive_file.write_text(html, encoding="utf-8")

    # .nojekyll is required for GitHub Pages to serve files without Jekyll processing
    nojekyll = output_path / ".nojekyll"
    if not nojekyll.exists():
        nojekyll.touch()

    print(f"[Dashboard] Generated: {out_file}")
    return str(out_file)


def _prepare_trend_chart(trend_history: dict) -> dict:
    """
    Prepare trend history for SVG chart rendering.

    Returns: {
        "dates": ["2024-03-01", ...],
        "categories": {
            "Kinderkleding": {"demand_scores": [7.2, ...], "avg_prices": [12.5, ...]},
            ...
        }
    }
    """
    if not trend_history:
        return {}

    dates = sorted(trend_history.keys())
    categories: dict[str, dict] = {}

    for date in dates:
        day_data = trend_history[date]
        for term, data in day_data.items():
            cat = data.get("category", term)
            if cat not in categories:
                categories[cat] = {"demand_scores": [], "avg_prices": [], "terms": set()}
            categories[cat]["terms"].add(term)

    # Fill data per date per category
    for cat in categories:
        categories[cat]["demand_scores"] = []
        categories[cat]["avg_prices"] = []
        for date in dates:
            day_data = trend_history[date]
            scores = []
            prices = []
            for term in categories[cat]["terms"]:
                if term in day_data:
                    scores.append(day_data[term]["demand_score"])
                    prices.append(day_data[term]["avg_price"])
            categories[cat]["demand_scores"].append(
                round(sum(scores) / len(scores), 1) if scores else 0
            )
            categories[cat]["avg_prices"].append(
                round(sum(prices) / len(prices), 2) if prices else 0
            )
        # Convert set to list for JSON serialization
        categories[cat]["terms"] = list(categories[cat]["terms"])

    return {
        "dates": dates,
        "categories": categories,
    }
