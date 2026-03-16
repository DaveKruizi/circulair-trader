"""
Pallet / bulk lot analyzer.

Uses Claude Vision to identify the contents of a pallet or bulk listing
(e.g. "pallet gemengde elektronica"), then searches Vinted for each
identified product type to estimate total resale value.

Flow:
1. Detect whether a listing is a pallet/bulk lot by keywords.
2. Send the listing image + title/description to Claude Vision.
3. Parse the structured product list Claude returns.
4. For each product type, call search_vinted_for_product().
5. Aggregate estimated resale value across all items.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional

import anthropic
import httpx

from src.budget_guard import register_usage, BudgetExceededError
from src.scrapers.vinted import search_vinted_for_product
from src.analysis.margin_calculator import estimate_sell_price_from_listings


# Keywords that indicate a listing contains multiple mixed products
_PALLET_KEYWORDS = {
    "pallet", "partij", "lot", "bulk", "container", "batch",
    "kist", "bak", "doos mixed", "gemengd", "assortiment",
    "diverse", "mixed", "wholesale", "voorraad", "retour",
    "retourgoederen", "veiling lot",
}


@dataclass
class PalletItem:
    product_type: str        # e.g. "Samsung smartphone"
    brand: str               # e.g. "Samsung"
    estimated_quantity: int  # e.g. 5
    condition: str           # e.g. "gebruikt", "nieuw", "onbekend"
    vinted_avg_price: float = 0.0   # from Vinted search
    vinted_listings_found: int = 0
    estimated_total_value: float = 0.0  # quantity * vinted_avg_price


@dataclass
class PalletAnalysis:
    items: list[PalletItem] = field(default_factory=list)
    total_estimated_quantity: int = 0
    total_estimated_resale_value: float = 0.0
    categories_found: list[str] = field(default_factory=list)
    confidence: float = 0.0   # 0.0–1.0
    analysis_notes: str = ""
    vinted_searches_done: int = 0


def is_pallet_listing(title: str, description: str) -> bool:
    """Return True if the listing appears to be a bulk/pallet lot."""
    text = (title + " " + description).lower()
    return any(kw in text for kw in _PALLET_KEYWORDS)


async def analyze_pallet(
    client: anthropic.AsyncAnthropic,
    image_url: str,
    title: str,
    description: str,
    buy_price: float = 0,
) -> Optional[PalletAnalysis]:
    """
    Analyze a pallet/bulk listing using Claude Vision + Vinted searches.

    Steps:
    1. Call Claude Vision with the listing image to identify contents.
    2. For each identified product type, search Vinted for price data.
    3. Return a PalletAnalysis with per-item breakdown and totals.

    Returns None if no image available or Claude call fails.
    """
    if not image_url:
        return None

    # ── Step 1: Download image ────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(image_url)
            if resp.status_code != 200:
                return None
            import base64
            img_b64 = base64.b64encode(resp.content).decode()
            media_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    except Exception as e:
        print(f"[Pallet] Kon afbeelding niet laden ({image_url[:60]}): {e}")
        return None

    # ── Step 2: Claude Vision — identify contents ─────────────────
    prompt = f"""Je analyseert een foto van een partij/pallet producten die te koop wordt aangeboden.

Aanbieding titel: {title}
Beschrijving: {description[:400] if description else "(geen beschrijving)"}
Inkoopprijs: {"€" + str(buy_price) if buy_price else "onbekend"}

Identificeer alle zichtbare producttypen op de foto. Geef een realistische schatting van:
- Welke producten (merk + type indien zichtbaar)
- Geschatte hoeveelheid per type
- Staat (nieuw / licht gebruikt / gebruikt / onbekend)

Antwoord UITSLUITEND in dit JSON formaat (geen andere tekst):
{{
  "confidence": 0.8,
  "notes": "Korte observatie over de partij",
  "items": [
    {{
      "product_type": "Nike sneakers maat onbekend",
      "brand": "Nike",
      "estimated_quantity": 8,
      "condition": "gebruikt"
    }},
    {{
      "product_type": "Adidas t-shirt",
      "brand": "Adidas",
      "estimated_quantity": 15,
      "condition": "nieuw"
    }}
  ]
}}

Wees conservatief met hoeveelheden als je het niet zeker weet. Maximum 10 itemtypes."""

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": img_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        register_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        raw_text = next((b.text for b in response.content if b.type == "text"), "")
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0]
        vision_data = json.loads(raw_text)
    except BudgetExceededError:
        raise
    except Exception as e:
        print(f"[Pallet] Vision analyse mislukt voor '{title[:50]}': {e}")
        return None

    raw_items = vision_data.get("items", [])
    if not raw_items:
        return None

    # ── Step 3: Vinted search per product type ────────────────────
    pallet_items: list[PalletItem] = []
    categories: set[str] = set()
    vinted_searches = 0

    for raw in raw_items[:10]:
        product_type = raw.get("product_type", "")
        brand = raw.get("brand", "")
        qty = max(1, int(raw.get("estimated_quantity", 1)))
        condition = raw.get("condition", "onbekend")

        if not product_type:
            continue

        item = PalletItem(
            product_type=product_type,
            brand=brand,
            estimated_quantity=qty,
            condition=condition,
        )

        # Vinted search for this specific product type
        # Run synchronously with small delay (we're already in async context)
        try:
            trend = search_vinted_for_product(product_type, buy_price=0)
            vinted_searches += 1
            time.sleep(1.2)  # rate limit

            if trend and trend.sample_listings:
                avg_price = estimate_sell_price_from_listings(trend.sample_listings)
                item.vinted_avg_price = avg_price
                item.vinted_listings_found = trend.listing_count
                item.estimated_total_value = round(avg_price * qty, 2)
                categories.add(trend.category)
        except Exception as e:
            print(f"[Pallet] Vinted search mislukt voor '{product_type}': {e}")

        pallet_items.append(item)

    total_qty = sum(i.estimated_quantity for i in pallet_items)
    total_value = sum(i.estimated_total_value for i in pallet_items)

    return PalletAnalysis(
        items=pallet_items,
        total_estimated_quantity=total_qty,
        total_estimated_resale_value=round(total_value, 2),
        categories_found=sorted(categories),
        confidence=float(vision_data.get("confidence", 0.5)),
        analysis_notes=vision_data.get("notes", ""),
        vinted_searches_done=vinted_searches,
    )
