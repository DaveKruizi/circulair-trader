"""
Condition classifier for LEGO listings.

Classifies text into one of three categories:
- NIB  : Nieuw In Doos (sealed, unopened)
- CIB  : Compleet In Doos (complete with box + manual, opened)
- incomplete : missing box, manual, or pieces
- unknown    : cannot determine from text
"""

NIB_KEYWORDS = [
    # Nederlands
    "sealed", "ongeopend", "geseald", "gesealed", "verzegeld", "verzegelde",
    "nooit geopend", "nieuw in verpakking", "nieuw in doos",
    "origineel verzegeld", "in originele verpakking",
    "nieuw en ongeopend", "ongebruikt", "ongebruikte",
    # Engels
    "new in box", "nib", "factory sealed", "brand new sealed",
    "unopened", "mint in box", "unused",
    # Duits
    "noch nie geöffnet", "versiegelt", "versiegelte", "ungeöffnet",
    "originalverpackt", "neu und ungeöffnet",
    "unbenutzt", "unbenutzte", "ungebraucht", "ungebrauchte",
    # Frans
    "scellé", "scellée", "jamais ouvert", "neuf scellé", "non ouvert",
    "inutilisé", "inutilisée", "non utilisé",
    # Spaans
    "precintado", "precintada", "sin abrir", "sellado", "nuevo precintado",
    "sin usar",
    # Italiaans
    "sigillato", "sigillata", "mai aperto", "nuovo sigillato", "non usato",
    # Portugees
    "selado", "nunca aberto", "fechado de fábrica",
    # Zweeds
    "förseglad", "oöppnad",
    # Deens
    "forseglet", "uåbnet",
    # Noors
    "uåpnet",
    # Pools
    "zapieczętowany", "nieotwarty", "fabrycznie zapieczętowany",
    # Tsjechisch / Slowaaks
    "zapečetěný", "neotevřený", "zapečatený",
    # Hongaars
    "bontatlan", "lezárt gyári",
    # Roemeens
    "sigilat", "nedeschis",
]

# Signalen die BEWIJZEN dat de set geopend of gebouwd is.
# Als deze aanwezig zijn naast een NIB-keyword, wint de contradictie —
# bijv. "ongebruikte onderdelen, exclusief doos" → geen NIB.
# Gebruik specifieke frasen (niet bare woorden) om false positives te vermijden:
# "nooit opgebouwd, gesealed" bevat "opgebouwd" maar is WEL NIB.
NIB_CONTRADICTIONS = [
    # Doos ontbreekt — een NIB-set zit altijd in de originele doos
    "exclusief doos", "zonder doos", "geen doos",
    "ohne box", "ohne karton",          # Duits
    "no box", "without box",            # Engels
    "sans boîte", "sans la boîte",      # Frans
    # Expliciet één keer gebouwd / geassembleerd — niet NIB
    "eénmaal opgebouwd", "eenmaal opgebouwd", "1x opgebouwd",
    "eénmaal gebouwd", "eenmaal gebouwd", "1x gebouwd",
    "display model", "displaymodel",
    "built once",                       # Engels
]

INCOMPLETE_KEYWORDS = [
    "zonder doos", "geen doos", "zonder handleiding", "geen handleiding",
    "losse steentjes", "niet compleet", "incompleet",
    "onderdelen ontbreken", "beschadigd", "kapot",
    "zonder instructies", "geen instructies", "steentjes alleen",
    "doos beschadigd", "handleiding mist", "los van de doos",
    "exclusief doos",
    "ohne box", "ohne anleitung", "ohne karton", "unvollständig",  # German
    "sans boîte", "incomplet",  # French
    "incomplete", "no box", "missing", "parts only",  # English
]

CIB_KEYWORDS = [
    # Compleetheid
    "compleet", "met doos", "met handleiding", "inclusief handleiding",
    "originele doos", "volledig", "met instructies", "inclusief instructies",
    "doos aanwezig", "handleiding aanwezig", "complete set",
    "met alle onderdelen", "volledig compleet",
    # Staat van gebruik — gebruikt maar in goede staat (NIET sealed)
    "nieuwstaat", "nieuw staat", "als nieuw", "zo goed als nieuw",
    "nagenoeg nieuw", "uitstekende staat", "perfecte staat",
    "goede staat", "zeer goede staat", "nette staat",
    # Gebouwd/gemonteerd — expliciet bewijs dat set geopend is
    "gebouwd", "opgebouwd", "in elkaar gezet", "gemonteerd",
    "zorgvuldig gebouwd", "1x gebouwd", "eenmalig gebouwd",
    "opnieuw te bouwen", "displaymodel", "display model",
    # Duits
    "vollständig", "mit box", "mit anleitung", "komplett",
    "gebaut", "zusammengebaut", "neuwertig", "wie neu",
    # Frans
    "complet", "avec boîte", "avec notice",
    # Engels
    "complete", "with box", "with instructions", "like new",
    "built once", "display model",
]


def classify_condition(title: str, description: str) -> str:
    """
    Classify listing condition based on title and description.

    Returns one of: "NIB", "CIB", "incomplete", "unknown"

    Priority: NIB > incomplete > CIB > unknown
    (incomplete beats CIB to prevent "compleet maar zonder doos" being CIB)
    """
    text = (title + " " + description).lower()

    if any(kw in text for kw in NIB_KEYWORDS):
        # Controleer of er tegenstrijdige signalen zijn die bewijzen dat de set
        # wél geopend/gebouwd is. Als dat zo is, geen NIB — doorvallen naar
        # CIB/incomplete. Voorbeeld: "ongebruikte onderdelen, exclusief doos"
        # triggert NIB via "ongebruikte", maar "exclusief doos" weerlegt dat.
        if not any(kw in text for kw in NIB_CONTRADICTIONS):
            return "NIB"

    has_incomplete = any(kw in text for kw in INCOMPLETE_KEYWORDS)
    has_cib = any(kw in text for kw in CIB_KEYWORDS)

    if has_incomplete and has_cib:
        # Conflict: "compleet maar zonder doos" -> incomplete wins
        return "incomplete"

    if has_incomplete:
        return "incomplete"

    if has_cib:
        return "CIB"

    return "unknown"


def condition_label(category: str) -> str:
    """Human-readable label for a condition category."""
    labels = {
        "NIB": "Nieuw in doos",
        "CIB": "Compleet in doos",
        "incomplete": "Incompleet",
        "unknown": "Onbekend",
    }
    return labels.get(category, category)


def condition_badge_color(category: str) -> str:
    """CSS color class for condition badge."""
    colors = {
        "NIB": "green",
        "CIB": "blue",
        "incomplete": "orange",
        "unknown": "gray",
    }
    return colors.get(category, "gray")
