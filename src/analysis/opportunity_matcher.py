"""
Opportunity matcher.

Combines scraped buying platform listings with Vinted trend data
to produce ranked Opportunity objects for the dashboard.

Uses Claude API to enrich each opportunity with a plain-language
summary and selling tips.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

import anthropic

from src.config import ANTHROPIC_API_KEY, MIN_SELL_PRICE, MIN_NET_MARGIN
from src.budget_guard import register_usage, BudgetExceededError
from src.analysis.margin_calculator import calculate_margin, estimate_sell_price_from_trends
from src.analysis.risk_scorer import score_opportunity, RiskScore


@dataclass
class Opportunity:
    # Source item info
    source_platform: str
    title: str
    buy_price: float
    buy_url: str
    image_url: str

    # Analysis
    estimated_sell_price: float
    net_profit: float
    margin_pct: float
    risk_score: float
    risk_label: str
    risk_flags: list[str]

    # Claude-generated insight
    summary: str
    selling_tips: str
    matched_trend: str  # Which Vinted trend category this matches

    # Breakdown
    shipping_cost: float
    vinted_commission: float

    # Meta
    days_listed: Optional[int] = None
    is_viable: bool = True
    margin_reason: str = ""


def _find_best_trend(title: str, description: str, trends: list) -> Optional[Any]:
    """Find the most relevant Vinted trend for a given item."""
    text = (title + " " + description).lower()
    best = None
    best_score = 0

    for trend in trends:
        words = trend.search_term.lower().split()
        score = sum(1 for w in words if w in text)
        # Category name match also counts
        if trend.category.lower() in text:
            score += 2
        if score > best_score:
            best_score = score
            best = trend

    return best if best_score > 0 else (trends[0] if trends else None)


async def _get_claude_insight(
    client: anthropic.AsyncAnthropic,
    title: str,
    buy_price: float,
    estimated_sell_price: float,
    platform: str,
    trend_name: str,
) -> tuple[str, str]:
    """
    Ask Claude for a plain-language opportunity summary and selling tips.
    Returns (summary, selling_tips).
    """
    prompt = f"""Je bent een ervaren tweedehands handelaar die verkoopt op Vinted.

Product: {title}
Inkoopplatform: {platform}
Inkoopprijs: €{buy_price:.2f}
Geschatte verkoopprijs Vinted: €{estimated_sell_price:.2f}
Trend categorie: {trend_name}

Geef in maximaal 2 zinnen:
1. Een korte samenvatting waarom dit een goede (of slechte) opportunity is.
2. 1-2 concrete verkooptips voor Vinted (titel, foto, beschrijving).

Antwoord in het Nederlands. Wees direct en praktisch."""

    try:
        response = await client.messages.create(
            model="claude-opus-4-6",
            max_tokens=300,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )
        # Registreer token gebruik en controleer budget
        register_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        text = next(
            (b.text for b in response.content if b.type == "text"), ""
        )
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        summary = lines[0] if lines else "Zie productdetails."
        tips = " ".join(lines[1:]) if len(lines) > 1 else "Gebruik heldere foto's en een goede beschrijving."
        return summary, tips
    except BudgetExceededError:
        raise  # Laat budget errors door — tool moet stoppen
    except Exception as e:
        print(f"[Claude] Error getting insight for '{title}': {e}")
        return "Analyse niet beschikbaar.", "Gebruik heldere foto's en een goede beschrijving."


async def _enrich_opportunities(
    opportunities: list[Opportunity],
) -> list[Opportunity]:
    """Enrich top opportunities with Claude insights (async, batched)."""
    if not ANTHROPIC_API_KEY:
        print("[Claude] No API key set — skipping AI enrichment.")
        return opportunities

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    # Only enrich top 10 to keep API costs low
    to_enrich = opportunities[:10]

    tasks = [
        _get_claude_insight(
            client,
            opp.title,
            opp.buy_price,
            opp.estimated_sell_price,
            opp.source_platform,
            opp.matched_trend,
        )
        for opp in to_enrich
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            continue
        summary, tips = result
        to_enrich[i].summary = summary
        to_enrich[i].selling_tips = tips

    return opportunities


def match_opportunities(
    buying_listings: list,
    vinted_trends: list,
    enrich_with_claude: bool = True,
) -> list[Opportunity]:
    """
    Match buying platform listings against Vinted trends and rank opportunities.

    Args:
        buying_listings: List of listing objects from any buying scraper.
        vinted_trends: List of VintedTrend objects.
        enrich_with_claude: Whether to call Claude API for summaries.

    Returns:
        List of Opportunity objects sorted by net_profit descending.
    """
    opportunities: list[Opportunity] = []

    for listing in buying_listings:
        title = getattr(listing, "title", "")
        buy_price = getattr(listing, "price", 0) or getattr(listing, "current_bid", 0)
        url = getattr(listing, "url", "")
        image_url = getattr(listing, "image_url", "")
        description = getattr(listing, "description", "")
        days_listed = getattr(listing, "days_listed", None)
        platform = getattr(listing, "source", "onbekend")

        if not title or buy_price <= 0:
            continue

        # Find best matching Vinted trend
        trend = _find_best_trend(title, description, vinted_trends)
        trend_name = trend.search_term if trend else "algemeen"
        vinted_demand = trend.demand_score if trend else 5.0

        # Estimate sell price
        estimated_sell = estimate_sell_price_from_trends(
            title, vinted_trends, buy_price=buy_price
        )
        if estimated_sell < MIN_SELL_PRICE:
            continue

        # Calculate margin
        margin = calculate_margin(buy_price, estimated_sell)
        if not margin.is_viable:
            continue

        # Score risk
        risk = score_opportunity(
            title=title,
            description=description,
            buy_price=buy_price,
            days_listed=days_listed,
            vinted_demand_score=vinted_demand,
            margin_result=margin,
        )

        opp = Opportunity(
            source_platform=platform,
            title=title,
            buy_price=buy_price,
            buy_url=url,
            image_url=image_url,
            estimated_sell_price=estimated_sell,
            net_profit=margin.net_profit,
            margin_pct=margin.margin_pct,
            risk_score=risk.total_score,
            risk_label=risk.label,
            risk_flags=risk.flags,
            summary="Analyse wordt geladen...",
            selling_tips="",
            matched_trend=trend_name,
            shipping_cost=margin.shipping_cost,
            vinted_commission=margin.vinted_commission,
            days_listed=days_listed,
            is_viable=margin.is_viable,
            margin_reason=margin.reason,
        )
        opportunities.append(opp)

    # Sort: risk_score * net_profit (balance risk and reward)
    opportunities.sort(
        key=lambda o: (o.risk_score * 0.4 + min(o.net_profit, 50) * 0.6),
        reverse=True,
    )

    # Enrich top results with Claude
    if enrich_with_claude and opportunities:
        opportunities = asyncio.run(_enrich_opportunities(opportunities))

    return opportunities
