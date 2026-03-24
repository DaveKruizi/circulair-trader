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
)


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
