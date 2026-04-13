"""
Inhoudsfilters voor LEGO-listings.

Detecteert twee categorieën die NIET mogen meewegen in prijsberekeningen:

  1. REPLICA / NAMAAK — geen originele LEGO (Lepin, Mould King, "compatibel", etc.)
  2. ACCESSOIRE     — accessoire bij een set, niet de set zelf
                     (verlichtingskit, display-box, etc.)

Beide functies returnen (True, "gematchte_keyword") bij een treffer,
of (False, "") als het item schoon is.

Strategie:
- Replica-check: titel én beschrijving (eerste 400 tekens) — namaak staat soms
  alleen in de omschrijving.  Voor dubbelzinnige woorden ("compatibel") wordt
  ALLEEN de titel gecheckt om false-positives te vermijden.
- Accessoire-check: ALLEEN titel — "verlichting" in een omschrijving kan ook
  betekenen dat het een goede eigenschap van de set is.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# REPLICA / NAMAAK
# ---------------------------------------------------------------------------

# Gecheckt in ZOWEL titel als beschrijving (onmiskenbaar nep-signaal)
_REPLICA_FULL: tuple[str, ...] = (
    "non lego",
    "non-lego",
    "niet lego",
    "niet-lego",
    "geen lego",
    "geen origineel",
    "niet origineel",
    "niet-origineel",
    "niet-originele",
    "niet originele",
    "nep lego",
    "nep-lego",
    "replica",
    "namaak",
    "bootleg",
    "knockoff",
    "knock-off",
    "kopie van lego",
    "off-brand",
    # Andere talen: niet-origineel
    "nicht original",       # Duits
    "nicht originale",      # Duits
    "non original",         # Engels / Frans
    "non-original",         # Engels
    "non originale",        # Italiaans / Frans
    "no original",          # Spaans
    "não original",         # Portugees
    # Bekende kloon-merken
    "lepin",
    "mould king",
    "mould-king",
    "wange",
    "xingbao",
    "banbao",
    "cada",
    "sembo",
    "doublee eagle",
    "double eagle",
    "ausini",
    "kazi",
    "enlighten",
    "sluban",
    "bricks",          # generieke kloon-term ("bricks set", "building bricks") — nooit originele LEGO
    # "vergelijkbaar met / soortgelijk aan Lego" — verkoper geeft zelf aan dat het geen LEGO is
    "vergelijkbaar met lego",
    "soortgelijk als lego",
    "soortgelijk aan lego",
    "lijkt op lego",
    "similar to lego",
    "comparable to lego",
    "lego-like",
    "lego like",
    "ähnlich wie lego",   # Duits
    "wie lego",           # Duits: "wie Lego" = "like Lego"
    "como lego",          # Spaans / Portugees
    "come lego",          # Italiaans
    "comme lego",         # Frans
    # "gelijk aan lego" = kwaliteit is hetzelfde als Lego → niet origineel
    "gelijk aan lego",
    "zelfde als lego",
    "net als lego",
    "net zo goed als lego",
    "kwaliteit van lego",
    "kwaliteit lego blokjes",
)

# Gecheckt ALLEEN in de titel (in een omschrijving kunnen ze onschuldig zijn)
_REPLICA_TITLE_ONLY: tuple[str, ...] = (
    "compatibel",
    "compatibile",   # Italiaanse variant (Vinted)
    "compatible",
    "lego-compatible",
    "lego compatible",
    "kopie",         # "kopie" kan in beschrijving staan als "geen kopie (= origineel)"
)


def is_replica(title: str, description: str) -> tuple[bool, str]:
    """
    Geeft (True, keyword) terug als de listing waarschijnlijk namaak is.
    Geeft (False, "") terug als het schoon lijkt.
    """
    title_low = title.lower()
    desc_low = description[:400].lower() if description else ""
    combined = title_low + " " + desc_low

    for kw in _REPLICA_FULL:
        if kw in combined:
            return True, kw

    for kw in _REPLICA_TITLE_ONLY:
        if kw in title_low:
            return True, kw

    return False, ""


# ---------------------------------------------------------------------------
# ACCESSOIRES
# ---------------------------------------------------------------------------

# Gecheckt ALLEEN in de titel — omschrijving kan positief over accessoires spreken
# terwijl het toch de echte set betreft ("compleet, inclusief verlichting")
_ACCESSORY_TITLE: tuple[str, ...] = (
    # Verlichtingskits
    "verlichtingsset",
    "verlichting set",
    "verlichting kit",
    "verlichtingkit",
    "lichtset",
    "licht set",
    "licht kit",
    "lightkit",
    "light kit",
    "led kit",
    "ledkit",
    "led-kit",
    "ledstrip",
    "led strip",
    "led verlichting",
    "led licht",
    "led lighting",
    "light my bricks",    # bekende LEGO verlichtingsmerk
    "lightailing",
    # Display-accessoires
    "displaybox",
    "display box",
    "display-box",
    "display case",
    "display-case",
    "vitrinekast",
    "vitrine kast",
    "glazen vitrine",
    # Losse onderdelen / spare parts
    "losse stenen",
    "losse onderdelen",
    "losse blokjes",
    "spare parts",
    "reserveonderdelen",
    "extra onderdelen",
    "extra stenen",
    "extra blokjes",
    # Stickers / handleidingen als zelfstandig product
    "stickerset",
    "sticker set",
    "sticker sheet",
    "sticker vel",
    # Figuurtjes / minifiguren als zelfstandig product (niet de set)
    "figuurtjes",
    "lego figuurtjes",
    "lego-figuurtjes",
    "poppetjes",
    "minifiguurtjes",
    "figurines only",       # Engels
    "minifigures only",     # Engels
    "minifig only",         # Engels
    "figuren only",         # Duits/Engels mix
    # Fotolijst / picture frame
    "fotolijst",
    "fotolijstje",
    "bilderrahmen",         # Duits
    "cadre photo",          # Frans
    "picture frame",        # Engels
    "photo frame",          # Engels
    "marco de fotos",       # Spaans
    "portaretrato",         # Spaans
    "cornice foto",         # Italiaans
    "cornice portafoto",    # Italiaans
    "ramka na zdjecia",     # Pools
    # Muurbeugel / wall mount
    "muurbeugel",
    "muursteun",
    "wandbeugel",
    "wandhalterung",        # Duits
    "wandhalter",           # Duits
    "support mural",        # Frans
    "fixation murale",      # Frans
    "wall mount",           # Engels
    "wall bracket",         # Engels
    "wall hanger",          # Engels
    "soporte de pared",     # Spaans
    "soporte mural",        # Spaans
    "staffa a parete",      # Italiaans
    "supporto parete",      # Italiaans
    "uchwyt scienny",       # Pools
    # Display-stand / plank (accessoire, niet het model zelf)
    "display stand",
    "display plank",
    "display standaard",
    "display shelf",
    "display hanger",
    "display houder",
    # Verlichtingsets extra (internationaal)
    "lighting kit",         # Engels (extra)
    "beleuchtungsset",      # Duits
    "beleuchtung set",      # Duits
    "kit eclairage",        # Frans (zonder accent, lowercase)
    "kit d'eclairage",      # Frans
    "kit éclairage",        # Frans (met accent)
    "kit d'éclairage",      # Frans (met accent + apostrof)
    "éclairage led",        # Frans variant
)


def is_bundle(title: str, description: str) -> tuple[bool, str]:
    """
    Geeft (True, reden) als de listing een bundel van meerdere sets is.
    Bundelprijzen zijn per definitie onbruikbaar voor prijsanalyse van één set.

    Twee detectie-methoden:
    1. 3+ verschillende LEGO-setnummers in titel+beschrijving samen
    2. Bundle-trefwoorden in de titel (collectie, bundel, lot, pakket + meervoud)
    """
    combined = (title + " " + description).lower()

    # Methode 1: tel unieke setnummers voorafgegaan door 'lego' of '#'
    set_numbers = set(re.findall(r'(?:lego\s*|#)(\d{4,6})', combined))
    if len(set_numbers) >= 3:
        return True, f"{len(set_numbers)} setnummers gevonden ({', '.join(sorted(set_numbers)[:3])}...)"

    # Methode 2: bundle-trefwoorden in de titel
    title_low = title.lower()
    bundle_keywords = (
        "collectie", "bundel", "bundle", "lot lego", "lego lot",
        "meerdere sets", "multiple sets", "sets te koop",
        "2 sets", "3 sets", "4 sets", "5 sets", "6 sets",
        "2 nieuwe sets", "3 nieuwe sets", "4 nieuwe sets", "5 nieuwe sets",
    )
    for kw in bundle_keywords:
        if kw in title_low:
            return True, f"bundle-trefwoord in titel: '{kw}'"

    return False, ""


def is_accessory(title: str) -> tuple[bool, str]:
    """
    Geeft (True, keyword) terug als de listing een accessoire lijkt te zijn
    (verlichtingskit, display-box, etc.) in plaats van de set zelf.
    Checkt ALLEEN de titel.
    """
    title_low = title.lower()

    for kw in _ACCESSORY_TITLE:
        if kw in title_low:
            return True, kw

    return False, ""
