"""
Tests voor de condition classifier.

Elke test is gebaseerd op een echte advertentie die fout werd geclassificeerd
of die als regressietest dient om correcte gevallen te bewaken.
"""

import pytest
from src.analysis.condition_classifier import classify_condition


# ---------------------------------------------------------------------------
# NIB — moet NIB blijven
# ---------------------------------------------------------------------------

class TestNIB:
    def test_sealed(self):
        assert classify_condition("LEGO 42099", "Nooit geopend, sealed, in originele verpakking") == "NIB"

    def test_factory_sealed(self):
        assert classify_condition("LEGO 10305 nieuw in doos", "Ongeopend, factory sealed") == "NIB"

    def test_ongebruikt_set_zelf(self):
        # "ongebruikt" beschrijft de SET, geen andere objecten → NIB
        assert classify_condition("LEGO 42096", "Ongebruikt, ongeopend, sealed") == "NIB"

    def test_nooit_geopend(self):
        assert classify_condition("LEGO Technic", "Nooit geopend, nieuw in doos") == "NIB"

    def test_nib_met_ongebruikte_stickers_en_nooit_gebouwd(self):
        # "ongebruikte stickers (set nooit gebouwd)" — NIB moet standhouden
        assert classify_condition(
            "LEGO 10305",
            "Ongeopend, factory sealed, ongebruikte stickers (set nooit gebouwd)"
        ) == "NIB"


# ---------------------------------------------------------------------------
# CIB — echte gevallen die fout als NIB werden geclassificeerd
# ---------------------------------------------------------------------------

class TestCIBFalsePositives:
    def test_eenkeer_opgebouwd_ongebruikt_stickervel(self):
        """Harley-Davidson geval: 'ongebruikt stickervel' triggerde NIB."""
        assert classify_condition(
            "Lego Creator Expert 10269 Harley-Davidson Fat Boy",
            "Deze set is compleet en in prima staat. De set is één keer opgebouwd "
            "en heeft altijd stofvrij gestaan. Inclusief ongebruikt origineel stickervel. "
            "Instructieboekje in smetteloze staat."
        ) == "CIB"

    def test_bmw_instructieboek_ongebruikt(self):
        """BMW geval: 'boek met instructies nieuw (ongebruikt)' triggerde NIB."""
        assert classify_condition(
            "LEGO BMW 42130",
            "1x in elkaar gezet.\nDoos aanwezig.\nBoek met instructies nieuw (ongebruikt).\nStikkers wel geplakt."
        ) == "CIB"

    def test_bouwwerk_reservestukjes(self):
        """'bouwwerk' + 'reservestukjes' + 'ongebruikte stickers' triggerde NIB."""
        assert classify_condition(
            "",
            "Schitterend bouwwerk. Urenlang plezier van deze mooie set. "
            "100% compleet. Met doos en reservestukjes en ongebruikte stickers voor de nummerplaten. "
            "Instructieboek aanwezig. Status zo goed als nieuw. Vaste prijs."
        ) == "CIB"

    def test_zorgvuldig_afgebroken(self):
        """Afgebouwd ≠ NIB; compleet met doos → CIB."""
        assert classify_condition(
            "Lego Creator Expert Mini Cooper 10242",
            "Deze set is zorgvuldig afgebroken en alle onderdelen zijn netjes op nummer "
            "in zakjes gesorteerd. De set is gegarandeerd geheel compleet met alle originele "
            "onderdelen, het originele bouwboekje en de originele doos. "
            "De stickers zijn nog nooit geplakt."
        ) == "CIB"

    def test_eenmaal_opgebouwd(self):
        assert classify_condition("LEGO 42099", "Eenmaal opgebouwd, in prima staat, met doos") == "CIB"

    def test_een_keer_gebouwd(self):
        assert classify_condition("LEGO Technic", "Een keer gebouwd, alles aanwezig") == "CIB"

    def test_zo_goed_als_nieuw(self):
        assert classify_condition("LEGO 75192", "Compleet, met doos, zo goed als nieuw") == "CIB"

    def test_in_elkaar_gezet(self):
        assert classify_condition("LEGO set", "1x in elkaar gezet, doos aanwezig") == "CIB"


# ---------------------------------------------------------------------------
# Incomplete
# ---------------------------------------------------------------------------

class TestIncomplete:
    def test_started_building_no_box(self):
        """42128 geval: 'bags still sealed' triggerde NIB ondanks 'box not included'."""
        assert classify_condition(
            "LEGO Technic 42128 Heavy-Duty Tow Truck",
            "I've started building it but unfortunately lost interest. "
            "The set is not fully assembled; most of the bags are still sealed. "
            "Original instructions included. Stickers not used. Box not included. Parts are clean."
        ) == "incomplete"

    def test_zonder_doos(self):
        assert classify_condition("LEGO set", "Compleet maar zonder doos") == "incomplete"

    def test_niet_compleet(self):
        assert classify_condition("LEGO set", "Niet compleet, onderdelen ontbreken") == "incomplete"
