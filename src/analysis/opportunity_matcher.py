"""
Opportunity matcher.

Combines scraped buying platform listings with Vinted trend data
to produce ranked Opportunity objects for the dashboard.

Uses Claude API to enrich each opportunity with a plain-language
summary and selling tips.
"""

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

import anthropic
import httpx

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

    # Volume (bulk)
    quantity_available: int = 1
    volume_bonus: float = 0.0

    # Deal tracking
    deal_id: str = ""
    is_new: bool = True
    first_seen: str = ""

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


def _generate_deal_id(title: str, url: str) -> str:
    """Generate a stable hash ID for a deal based on title + URL."""
    raw = f"{title.lower().strip()}|{url.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


async def _verify_product_match_vision(
    client: anthropic.AsyncAnthropic,
    buy_image_url: str,
    vinted_sample_urls: list[str],
    product_title: str,
) -> dict:
    """
    Use Claude Vision to verify if a buying listing matches Vinted samples.

    Returns dict with 'is_match' (bool), 'confidence' (0-1), 'reason' (str).
    """
    if not buy_image_url or not vinted_sample_urls:
        return {"is_match": True, "confidence": 0.5, "reason": "Geen afbeeldingen beschikbaar voor vergelijking"}

    # Download images (max 3 Vinted samples)
    image_contents = []
    async with httpx.AsyncClient(timeout=10) as http:
        # Buy image
        try:
            resp = await http.get(buy_image_url)
            if resp.status_code == 200:
                import base64
                buy_b64 = base64.b64encode(resp.content).decode()
                media_type = resp.headers.get("content-type", "image/jpeg")
                image_contents.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": buy_b64},
                })
        except Exception:
            return {"is_match": True, "confidence": 0.5, "reason": "Kon inkoopafbeelding niet laden"}

        # Vinted sample images (max 2)
        for url in vinted_sample_urls[:2]:
            try:
                resp = await http.get(url)
                if resp.status_code == 200:
                    import base64
                    sample_b64 = base64.b64encode(resp.content).decode()
                    media_type = resp.headers.get("content-type", "image/jpeg")
                    image_contents.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": sample_b64},
                    })
            except Exception:
                continue

    if len(image_contents) < 2:
        return {"is_match": True, "confidence": 0.5, "reason": "Te weinig afbeeldingen voor vergelijking"}

    prompt_text = f"""Je bent een expert in tweedehands producten. Vergelijk de EERSTE afbeelding (inkoopproduct) met de overige afbeeldingen (Vinted referenties).

Product titel: {product_title}

Beoordeel:
1. Is dit exact hetzelfde product (merk, model, variant)?
2. Geef een confidence score van 0.0 tot 1.0
3. Leg kort uit waarom wel/niet

Antwoord ALLEEN in dit JSON formaat:
{{"is_match": true/false, "confidence": 0.8, "reason": "korte uitleg"}}"""

    image_contents.append({"type": "text", "text": prompt_text})

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": image_contents}],
        )
        register_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        text = next((b.text for b in response.content if b.type == "text"), "{}")
        import json
        # Extract JSON from response
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(text)
        return {
            "is_match": result.get("is_match", True),
            "confidence": float(result.get("confidence", 0.5)),
            "reason": result.get("reason", ""),
        }
    except BudgetExceededError:
        raise
    except Exception as e:
        print(f"[Vision] Error verifying match for '{product_title}': {e}")
        return {"is_match": True, "confidence": 0.5, "reason": "Vision check mislukt"}


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
    negative_feedback: list[dict] = None,
    seen_deals: dict = None,
) -> list[Opportunity]:
    """
    Match buying platform listings against Vinted trends and rank opportunities.

    Args:
        buying_listings: List of listing objects from any buying scraper.
        vinted_trends: List of VintedTrend objects.
        enrich_with_claude: Whether to call Claude API for summaries.
        negative_feedback: List of negative feedback dicts from GitHub Issues.
        seen_deals: Dict of previously seen deal IDs for tracking new vs returning.

    Returns:
        List of Opportunity objects sorted by combined score descending.
    """
    if negative_feedback is None:
        negative_feedback = []
    if seen_deals is None:
        seen_deals = {}

    # Build list of rejected patterns from feedback
    rejected_patterns = [fb.get("reason", "").lower() for fb in negative_feedback if fb.get("reason")]

    opportunities: list[Opportunity] = []

    for listing in buying_listings:
        title = getattr(listing, "title", "")
        buy_price = getattr(listing, "price", 0) or getattr(listing, "current_bid", 0)
        url = getattr(listing, "url", "")
        image_url = getattr(listing, "image_url", "")
        description = getattr(listing, "description", "")
        days_listed = getattr(listing, "days_listed", None)
        platform = getattr(listing, "source", "onbekend")
        quantity = getattr(listing, "quantity_available", 1) or 1

        if not title or buy_price <= 0:
            continue

        # Skip items matching negative feedback patterns
        title_lower = title.lower()
        if any(pattern and pattern in title_lower for pattern in rejected_patterns):
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

        # Volume bonus: reward bulk availability
        volume_bonus = min(quantity, 10) * 1.5 if quantity > 1 else 0.0

        # Deal ID and new/returning tracking
        deal_id = _generate_deal_id(title, url)
        is_new = deal_id not in seen_deals

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
            quantity_available=quantity,
            volume_bonus=volume_bonus,
            deal_id=deal_id,
            is_new=is_new,
            first_seen=seen_deals.get(deal_id, {}).get("first_seen", ""),
            days_listed=days_listed,
            is_viable=margin.is_viable,
            margin_reason=margin.reason,
        )
        opportunities.append(opp)

    # Sort: balance risk, profit, and volume
    opportunities.sort(
        key=lambda o: (o.risk_score * 0.3 + min(o.net_profit, 50) * 0.4 + o.volume_bonus * 0.3),
        reverse=True,
    )

    # Vision verification for top 5 (if images available and Claude enabled)
    if enrich_with_claude and opportunities and ANTHROPIC_API_KEY:
        opportunities = asyncio.run(
            _verify_and_enrich(opportunities, vinted_trends, negative_feedback)
        )

    return opportunities


async def _verify_and_enrich(
    opportunities: list[Opportunity],
    vinted_trends: list,
    negative_feedback: list[dict],
) -> list[Opportunity]:
    """Verify top matches with Vision, then enrich with Claude insights."""
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    # Vision verification for top 5 opportunities with images
    to_verify = [o for o in opportunities[:10] if o.image_url][:5]
    # Build trend sample image map
    trend_images = {}
    for trend in vinted_trends:
        if hasattr(trend, "sample_listings"):
            urls = [s.photo_url for s in trend.sample_listings if s.photo_url]
            if urls:
                trend_images[trend.search_term] = urls

    verified_ids = set()
    for opp in to_verify:
        sample_urls = trend_images.get(opp.matched_trend, [])
        if not sample_urls:
            continue
        try:
            result = await _verify_product_match_vision(
                client, opp.image_url, sample_urls, opp.title
            )
            if not result["is_match"] and result["confidence"] >= 0.7:
                opp.is_viable = False
                opp.risk_flags.append(f"Vision: geen match ({result['reason']})")
            verified_ids.add(opp.deal_id)
        except BudgetExceededError:
            break
        except Exception:
            continue

    # Remove non-viable after vision check
    opportunities = [o for o in opportunities if o.is_viable]

    # Enrich with Claude insights
    await _enrich_opportunities(opportunities)
    return opportunities
