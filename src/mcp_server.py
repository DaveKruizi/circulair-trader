"""
Circulair Trader MCP Server.

Exposes tools that Claude can call via MCP (Model Context Protocol)
for on-demand trading research sessions.

Usage with Claude Desktop:
  Add to claude_desktop_config.json:
  {
    "mcpServers": {
      "circulair-trader": {
        "command": "python",
        "args": ["/path/to/circulair-trader/src/mcp_server.py"],
        "env": { "ANTHROPIC_API_KEY": "..." }
      }
    }
  }
"""

import json
import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.scrapers.vinted import scrape_vinted_trends
from src.scrapers.marktplaats import scrape_marktplaats
from src.scrapers.troostwijk import scrape_troostwijk
from src.scrapers.stocklear import scrape_stocklear
from src.scrapers.merkandi import scrape_merkandi
from src.scrapers.partijhandelaren import scrape_partijhandelaren
from src.scrapers.onlineveilingmeester import scrape_onlineveilingmeester
from src.analysis.margin_calculator import calculate_margin
from src.analysis.risk_scorer import score_opportunity
from src.analysis.opportunity_matcher import match_opportunities
from src.config import MIN_SELL_PRICE, MIN_NET_MARGIN, VINTED_COMMISSION_PCT


app = Server("circulair-trader")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_vinted_trends",
            description=(
                "Scrape Vinted.nl voor actuele trends: welke producten worden veel "
                "aangeboden, voor welke prijs, en wat is de vraag? "
                "Gebruik dit om te weten wat goed verkoopt."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "max_per_term": {
                        "type": "integer",
                        "description": "Max aantal listings per zoekterm (default: 20)",
                        "default": 20,
                    }
                },
            },
        ),
        Tool(
            name="search_buying_platforms",
            description=(
                "Zoek op alle Nederlandse inkoopplatforms (Marktplaats, Troostwijk, "
                "Stocklear, Merkandi, PartijHandelaren, Onlineveilingmeester) naar items "
                "die matchen met Vinted-trends. Geeft een lijst van opportunities terug."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Zoektermen (leeg = gebruik Vinted trends automatisch)",
                    },
                    "max_buy_price": {
                        "type": "number",
                        "description": "Maximum inkoopprijs in euro (default: 50)",
                        "default": 50,
                    },
                    "platforms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Welke platforms te doorzoeken (leeg = allemaal)",
                    },
                },
            },
        ),
        Tool(
            name="calculate_margin",
            description=(
                "Bereken de netto winstmarge voor een specifiek product. "
                "Geeft een volledige kostenberekening incl. verzending en Vinted-commissie."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "buy_price": {
                        "type": "number",
                        "description": "Inkoopprijs in euro",
                    },
                    "sell_price": {
                        "type": "number",
                        "description": "Verwachte verkoopprijs op Vinted in euro",
                    },
                    "shipping_cost": {
                        "type": "number",
                        "description": "Verzendkosten (default: 5 euro)",
                        "default": 5,
                    },
                },
                "required": ["buy_price", "sell_price"],
            },
        ),
        Tool(
            name="get_daily_report",
            description=(
                "Genereer het complete dagelijkse opportunity rapport: "
                "scrape alle bronnen, analyseer trends, bereken marges en risicoscores, "
                "en geef de top-10 beste opportunities terug. "
                "Dit is de complete workflow in één aanroep."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "top_n": {
                        "type": "integer",
                        "description": "Aantal top opportunities om terug te geven (default: 10)",
                        "default": 10,
                    },
                    "generate_html": {
                        "type": "boolean",
                        "description": "Ook HTML dashboard genereren (default: true)",
                        "default": True,
                    },
                },
            },
        ),
        Tool(
            name="score_item",
            description=(
                "Geef een risico/kans score voor een specifiek product dat je overweegt in te kopen. "
                "Geeft score 0-10 en specifieke waarschuwingen."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Naam/titel van het product",
                    },
                    "description": {
                        "type": "string",
                        "description": "Beschrijving van het product",
                        "default": "",
                    },
                    "buy_price": {
                        "type": "number",
                        "description": "Inkoopprijs",
                    },
                    "days_listed": {
                        "type": "integer",
                        "description": "Hoeveel dagen al te koop (optioneel)",
                    },
                },
                "required": ["title", "buy_price"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls from MCP client."""

    if name == "get_vinted_trends":
        max_per_term = arguments.get("max_per_term", 20)
        trends = scrape_vinted_trends(max_per_term=max_per_term)

        output = f"## Vinted Trends ({len(trends)} categorieën)\n\n"
        for t in trends[:10]:
            output += f"### {t.search_term} ({t.category})\n"
            output += f"- Vraag score: {t.demand_score}/10\n"
            output += f"- Gem. prijs: €{t.avg_price:.2f} (€{t.min_price:.2f} – €{t.max_price:.2f})\n"
            output += f"- Actieve listings: {t.listing_count}\n"
            output += f"- Gem. favorieten: {t.avg_favorites}\n\n"

        return [TextContent(type="text", text=output)]

    elif name == "search_buying_platforms":
        search_terms = arguments.get("search_terms", [])
        max_buy_price = arguments.get("max_buy_price", 50)
        platforms = arguments.get("platforms", [])

        # Default: search all platforms
        if not platforms:
            platforms = ["marktplaats", "troostwijk", "stocklear",
                        "merkandi", "partijhandelaren", "onlineveilingmeester"]

        all_listings = []

        if "marktplaats" in platforms:
            terms = search_terms or ["vintage", "tweedehands kleding", "sieraden"]
            results = scrape_marktplaats(terms, max_price=max_buy_price)
            all_listings.extend(results)

        if "troostwijk" in platforms:
            results = scrape_troostwijk(max_current_bid=max_buy_price)
            all_listings.extend(results)

        if "stocklear" in platforms:
            results = scrape_stocklear()
            all_listings.extend(results)

        if "merkandi" in platforms:
            results = scrape_merkandi()
            all_listings.extend(results)

        if "partijhandelaren" in platforms:
            results = scrape_partijhandelaren()
            all_listings.extend(results)

        if "onlineveilingmeester" in platforms:
            results = scrape_onlineveilingmeester()
            all_listings.extend(results)

        output = f"## Inkoopplatforms — {len(all_listings)} listings gevonden\n\n"
        for listing in all_listings[:20]:
            title = getattr(listing, "title", "")
            price = getattr(listing, "price", 0) or getattr(listing, "current_bid", 0)
            url = getattr(listing, "url", "")
            source = getattr(listing, "source", "")
            output += f"- **{title}** — €{price:.2f} [{source}]({url})\n"

        return [TextContent(type="text", text=output)]

    elif name == "calculate_margin":
        buy_price = arguments["buy_price"]
        sell_price = arguments["sell_price"]
        shipping = arguments.get("shipping_cost", 5)

        result = calculate_margin(buy_price, sell_price, shipping_cost=shipping)

        output = f"""## Margecalculatie

| Post | Bedrag |
|------|--------|
| Verkoopprijs | €{result.estimated_sell_price:.2f} |
| Inkoopprijs | -€{result.buy_price:.2f} |
| Verzendkosten | -€{result.shipping_cost:.2f} |
| Vinted commissie ({result.vinted_commission_pct}%*) | -€{result.vinted_commission:.2f} |
| Abonnement per verkoop | -€{result.subscription_per_sale:.2f} |
| **Netto winst** | **€{result.net_profit:.2f}** |
| Marge | {result.margin_pct:.1f}% |

*Let op: commissie is een placeholder. Pas aan zodra je je Vinted Pro tarief weet.

**Haalbaar:** {"✅ Ja" if result.is_viable else "❌ Nee"} — {result.reason}
"""
        return [TextContent(type="text", text=output)]

    elif name == "score_item":
        title = arguments["title"]
        description = arguments.get("description", "")
        buy_price = arguments["buy_price"]
        days_listed = arguments.get("days_listed")

        risk = score_opportunity(
            title=title,
            description=description,
            buy_price=buy_price,
            days_listed=days_listed,
        )

        output = f"""## Risicoscore: {title}

**Score: {risk.total_score}/10 — {risk.label}**

| Factor | Score |
|--------|-------|
| Vraag (Vinted) | {risk.demand_score}/10 |
| Versheid listing | {risk.freshness_score}/10 |
| Prijssanity | {risk.price_sanity_score}/10 |
| Conditie/inspanning | {risk.condition_score}/10 |
"""
        if risk.flags:
            output += "\n**Waarschuwingen:**\n"
            for flag in risk.flags:
                output += f"- ⚠️ {flag}\n"

        return [TextContent(type="text", text=output)]

    elif name == "get_daily_report":
        top_n = arguments.get("top_n", 10)
        generate_html = arguments.get("generate_html", True)

        # Step 1: Vinted trends
        print("[MCP] Scraping Vinted trends...")
        trends = scrape_vinted_trends(max_per_term=15)

        # Step 2: All buying platforms
        print("[MCP] Scraping buying platforms...")
        all_listings = []
        search_terms = [t.search_term for t in trends[:5]]

        all_listings.extend(scrape_marktplaats(search_terms, max_price=50))
        all_listings.extend(scrape_troostwijk(max_current_bid=50))
        all_listings.extend(scrape_stocklear())
        all_listings.extend(scrape_merkandi())
        all_listings.extend(scrape_partijhandelaren())
        all_listings.extend(scrape_onlineveilingmeester())

        # Step 3: Match and rank
        print("[MCP] Matching opportunities...")
        opportunities = match_opportunities(all_listings, trends, enrich_with_claude=True)

        # Step 4: Optionally generate dashboard
        dashboard_path = None
        if generate_html and opportunities:
            from src.dashboard.generator import generate_dashboard
            sources = list({getattr(l, "source", "?") for l in all_listings})
            dashboard_path = generate_dashboard(opportunities, trends, sources)

        # Format output
        output = f"# Dagelijks Rapport — {len(opportunities)} opportunities\n\n"
        output += f"Vinted trends gescand: {len(trends)}\n"
        output += f"Listings gevonden: {len(all_listings)}\n"
        output += f"Viable opportunities: {len(opportunities)}\n\n"

        if dashboard_path:
            output += f"Dashboard gegenereerd: `{dashboard_path}`\n\n"

        output += f"## Top {min(top_n, len(opportunities))} Opportunities\n\n"

        for i, opp in enumerate(opportunities[:top_n], 1):
            output += f"### {i}. {opp.title}\n"
            output += f"- Platform: {opp.source_platform}\n"
            output += f"- Inkoopprijs: €{opp.buy_price:.2f}\n"
            output += f"- Verwachte verkoopprijs: €{opp.estimated_sell_price:.2f}\n"
            output += f"- Netto winst: **€{opp.net_profit:.2f}** ({opp.margin_pct:.0f}%)\n"
            output += f"- Risicoscore: {opp.risk_score}/10 ({opp.risk_label})\n"
            output += f"- Trend match: {opp.matched_trend}\n"
            if opp.summary:
                output += f"- Samenvatting: {opp.summary}\n"
            output += f"- Link: {opp.buy_url}\n\n"

        return [TextContent(type="text", text=output)]

    else:
        return [TextContent(type="text", text=f"Onbekende tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
