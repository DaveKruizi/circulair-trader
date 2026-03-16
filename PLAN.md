# Implementatieplan: Dashboard Verbeteringen v2

## Overzicht wijzigingen
1. **Productcategorieën** → kinderkleding, speelgoed, kinderboeken
2. **Exacte productvergelijking** met Claude Vision (afbeeldingen)
3. **Volume-detectie** — prioriteit aan bulk-aanbod
4. **4-weken trendanalyse** met grafiekjes (i.p.v. dagelijks)
5. **Feedback-systeem** via GitHub Issues (👍/👎 + uitleg)
6. **Favorieten** met ster-knop + aparte pagina + grijs als uitverkocht
7. **Deal-categorisatie** — nieuw vandaag / nog beschikbaar / favorieten

---

## Fase 1: Categorieën & zoektermen aanpassen

### `src/scrapers/vinted.py`
- Vervang de 12 huidige zoektermen door kindercategorieën:
  - Kinderkleding: "kinderkleding", "babykleding", "kinderjas", "kinderschoenen"
  - Speelgoed: "speelgoed", "duplo", "playmobil", "kinderpuzzel"
  - Kinderboeken: "kinderboeken", "prentenboeken", "leesboeken kinderen"
- Pas `VINTED_CATEGORIES` dict aan

### `src/scrapers/marktplaats.py`
- Pas zoektermen aan naar dezelfde kindercategorieën
- Voeg Marktplaats-categorie-ID's toe voor kinderen

### Overige scrapers
- Pas zoektermen/categorieën aan waar relevant (Troostwijk, Merkandi, etc.)

---

## Fase 2: Exacte productvergelijking met afbeeldingen

### `src/analysis/opportunity_matcher.py`
- Nieuwe functie: `verify_product_match(buying_image_url, vinted_image_urls) -> MatchResult`
- Gebruikt Claude Vision om afbeeldingen te vergelijken
- Prompt: "Zijn dit exact dezelfde producten? Let op merk, model, kleur, maat, staat."
- Retourneert: `confidence_score` (0-1), `is_exact_match` (bool), `reason` (str)
- Alleen opportunities met `confidence >= 0.8` worden meegenomen
- Budget: max 5 vision-calls per run (kosten beheersen)

### `src/scrapers/*.py`
- Zorg dat alle scrapers `image_url` meegeven (de meeste doen dit al)

---

## Fase 3: Volume-detectie

### `src/scrapers/vinted.py` + `marktplaats.py`
- Nieuwe velden: `quantity_available`, `seller_stock_count`
- Vinted: check of verkoper meerdere van hetzelfde heeft
- Marktplaats: parse "aantal" veld als aanwezig

### `src/analysis/opportunity_matcher.py`
- Nieuwe scoring-factor: `volume_bonus`
- Items met quantity > 1 krijgen hogere score
- Formule: `volume_bonus = min(quantity, 10) * 1.5`
- Aangepaste ranking: `risk_score * 0.3 + profit * 0.4 + volume_bonus * 0.3`

---

## Fase 4: 4-weken trendanalyse + grafiek

### `output/trend_history.json`
- Nieuw bestand in repo, groeit dagelijks
- Structuur: `{ "2024-03-16": { "kinderkleding": { "avg_price": 12, "demand_score": 7, "listing_count": 45 }, ... } }`
- Max 28 dagen bewaard (rolling window)

### `src/main.py`
- Na stap 1: lees `trend_history.json`, voeg vandaag toe, schrijf terug
- Bereken week-over-week verandering per categorie

### `src/dashboard/templates/dashboard.html`
- Trendgrafiek met inline SVG (geen externe libraries nodig)
- Lijn per categorie over 4 weken
- X-as: datum, Y-as: demand_score of avg_price

---

## Fase 5: Feedback-systeem via GitHub Issues

### `src/dashboard/templates/dashboard.html`
- Per opportunity-card: 👍 en 👎 knoppen
- 👍 = "Goede deal" → maakt GitHub Issue met label `feedback-positive`
- 👎 = "Niet relevant" → opent modal voor uitleg → maakt Issue met label `feedback-negative`
- Issue body bevat: product titel, URL, prijs, reden (bij 👎)
- Gebruikt GitHub REST API vanuit browser (vereist PAT, opgeslagen in localStorage)

### Eerste keer setup
- Dashboard toont "Stel je GitHub token in" prompt als er geen token in localStorage zit
- Link naar GitHub PAT-aanmaakpagina met juiste scopes (repo:issues)

### `src/main.py` (feedback teruglezen)
- Bij start: lees open Issues met label `feedback-negative` via GitHub API
- Extraheer patronen: welke producten/categorieën worden afgewezen + waarom
- Geef deze context mee aan Claude bij enrichment
- Sluit verwerkte Issues automatisch (label: `feedback-processed`)

### `src/analysis/opportunity_matcher.py`
- Nieuwe parameter: `negative_feedback: list[dict]`
- Filter opportunities die matchen met eerder afgewezen patronen
- Claude prompt uitbreiden: "Deze producttypes zijn eerder afgewezen: {feedback}. Houd hier rekening mee."

---

## Fase 6: Favorieten-systeem

### `src/dashboard/templates/dashboard.html`
- ⭐ knop per opportunity-card
- Klik → maakt GitHub Issue met label `favorite`
- Issue body: volledige product-info (titel, URL, prijs, afbeelding, datum)

### Favorieten-pagina
- Nieuw bestand: `output/favorieten.html`
- Lijst van alle open Issues met label `favorite`
- Per favoriet: productinfo + link naar originele advertentie

### `src/main.py`
- Check of favoriete URLs nog bereikbaar zijn (HTTP HEAD request)
- Als 404/niet beschikbaar → update Issue met label `uitverkocht`
- Dashboard toont deze als grijs/doorgestreept

### `src/dashboard/generator.py`
- Genereer ook `favorieten.html` naast `index.html`

---

## Fase 7: Deal-categorisatie in dashboard

### `output/seen_deals.json`
- Houdt bij welke deals eerder zijn getoond + datum eerste verschijning
- Structuur: `{ "deal_id_hash": { "first_seen": "2024-03-14", "last_seen": "2024-03-16", "title": "..." } }`

### `src/main.py`
- Vergelijk huidige opportunities met `seen_deals.json`
- Tag elke deal: `is_new` (vandaag voor het eerst) of `is_returning` (eerder gezien, nog beschikbaar)

### `src/dashboard/templates/dashboard.html`
- 3 tabs bovenaan:
  - **🆕 Nieuw vandaag** — deals die voor het eerst verschijnen
  - **📦 Nog beschikbaar** — deals van eerdere dagen die nog live zijn
  - **⭐ Favorieten** — gemarkeerde deals (uit GitHub Issues)
- Badge met aantal per tab
- Filter werkt samen met bestaande risico/platform filters

---

## Technische details

### GitHub Issues API (vanuit browser)
```javascript
// Feedback aanmaken
fetch('https://api.github.com/repos/DaveKruizi/circulair-trader/issues', {
  method: 'POST',
  headers: {
    'Authorization': `token ${localStorage.getItem('gh_pat')}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    title: `[feedback] ${dealTitle}`,
    body: feedbackBody,
    labels: ['feedback-positive'] // of 'feedback-negative'
  })
});
```

### GitHub Issues API (vanuit workflow)
```python
# Feedback ophalen in main.py
import httpx
issues = httpx.get(
    'https://api.github.com/repos/DaveKruizi/circulair-trader/issues',
    params={'labels': 'feedback-negative', 'state': 'open'},
    headers={'Authorization': f'token {GITHUB_TOKEN}'}
).json()
```

### Budget-impact
- Vision calls: ~$0.01 per afbeeldingsvergelijking → max 5 per run = $0.05/dag
- Tekst enrichment: bestaande ~$0.10/dag
- Totaal: ~$4.50/maand (binnen €10 budget)

### Bestanden die worden aangemaakt/gewijzigd
| Bestand | Actie |
|---------|-------|
| `src/scrapers/vinted.py` | Categorieën wijzigen |
| `src/scrapers/marktplaats.py` | Zoektermen wijzigen |
| `src/analysis/opportunity_matcher.py` | Vision matching, volume scoring, feedback |
| `src/main.py` | Trendhistorie, feedback loop, deal tracking |
| `src/dashboard/generator.py` | Favorieten-pagina, deal-categorisatie |
| `src/dashboard/templates/dashboard.html` | Tabs, feedback knoppen, favorieten, grafiek |
| `src/config.py` | GitHub repo config toevoegen |
| `output/trend_history.json` | Nieuw: trenddata opslag |
| `output/seen_deals.json` | Nieuw: deal tracking |
| `.github/workflows/daily-dashboard.yml` | GITHUB_TOKEN doorgeven |
