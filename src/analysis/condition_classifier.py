"""
Condition classifier for LEGO listings.

Classifies text into one of three categories:
- NIB  : Nieuw In Doos (sealed, unopened)
- CIB  : Compleet In Doos (complete with box + manual, opened)
- incomplete : missing box, manual, or pieces
- unknown    : cannot determine from text
"""

NIB_KEYWORDS = [
    "sealed", "ongeopend", "new in box", "nib", "verzegeld",
    "nooit geopend", "nieuw in verpakking", "nieuw in doos",
    "factory sealed", "geseald", "origineel verzegeld",
    "noch nie geöffnet", "versiegelt", "ungeöffnet",  # German
    "scellé", "jamais ouvert",  # French
]

INCOMPLETE_KEYWORDS = [
    "zonder doos", "geen doos", "zonder handleiding", "geen handleiding",
    "losse steentjes", "niet compleet", "incompleet",
    "onderdelen ontbreken", "beschadigd", "kapot",
    "zonder instructies", "geen instructies", "steentjes alleen",
    "doos beschadigd", "handleiding mist", "los van de doos",
    "ohne box", "ohne anleitung", "ohne karton", "unvollständig",  # German
    "sans boîte", "incomplet",  # French
    "incomplete", "no box", "missing", "parts only",  # English
]

CIB_KEYWORDS = [
    "compleet", "met doos", "met handleiding", "inclusief handleiding",
    "originele doos", "volledig", "met instructies", "inclusief instructies",
    "doos aanwezig", "handleiding aanwezig", "complete set",
    "met alle onderdelen", "volledig compleet",
    "vollständig", "mit box", "mit anleitung", "komplett",  # German
    "complet", "avec boîte", "avec notice",  # French
    "complete", "with box", "with instructions",  # English
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
