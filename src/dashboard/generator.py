"""
Dashboard generator.

Renders the Jinja2 HTML template with opportunity and trend data.
Writes output to the configured OUTPUT_DIR.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.config import OUTPUT_DIR
from src.budget_guard import get_current_cost


TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_dashboard(
    opportunities: list,
    trends: list,
    sources_scanned: list[str],
) -> str:
    """
    Render the dashboard HTML and write to output directory.

    Args:
        opportunities: List of Opportunity objects.
        trends: List of VintedTrend objects.
        sources_scanned: List of platform names that were scraped.

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

    stats = {
        "total_opportunities": len(viable_opps),
        "best_profit": f"{max(profits):.2f}" if profits else "0.00",
        "avg_profit": f"{sum(profits) / len(profits):.2f}" if profits else "0.00",
        "low_risk_count": sum(1 for o in viable_opps if o.risk_score >= 7.5),
        "sources_scanned": len(sources_scanned),
    }

    html = template.render(
        opportunities=viable_opps[:20],  # Top 20 on dashboard
        trends=trends,
        stats=stats,
        generated_at=now.strftime("%d %b %Y, %H:%M"),
        next_update=next_run.strftime("%d %b %Y, %H:%M"),
        date_label=now.strftime("%d %B %Y"),
        api_cost=get_current_cost(),
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
