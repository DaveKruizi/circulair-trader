"""
Tests voor content filters: replica, accessoire, bundel-detectie.
"""

import pytest
from src.analysis.content_filters import is_replica, is_accessory, is_bundle


class TestReplica:
    def test_vergelijkbaar_met_lego(self):
        """Kloon-set die zichzelf als 'vergelijkbaar met Lego Technic' beschrijft."""
        flagged, kw = is_replica(
            "Bouwpakket Porsche 911 GT3 RS",
            "Te koop: een bouwpakket vergelijkbaar met Lego Technic. Modelnummer 8156."
        )
        assert flagged, f"Verwacht replica, keyword: {kw!r}"

    def test_lepin(self):
        flagged, _ = is_replica("Lepin 05132 Millennium Falcon", "")
        assert flagged

    def test_mould_king(self):
        flagged, _ = is_replica("Mould King Technic set", "")
        assert flagged

    def test_bricks(self):
        flagged, _ = is_replica("Building Bricks Technic set compatible", "")
        assert flagged

    def test_similar_to_lego_english(self):
        flagged, _ = is_replica("Porsche building set", "Similar to Lego Technic, great quality")
        assert flagged

    def test_echte_lego_niet_geflagged(self):
        flagged, _ = is_replica("LEGO Technic 42096 Porsche 911 RSR", "Origineel LEGO, sealed, nieuw in doos.")
        assert not flagged

    def test_compatibel_in_titel(self):
        """'compatibel' in titel → replica."""
        flagged, _ = is_replica("LEGO compatibel bouwset", "Geweldige set")
        assert flagged

    def test_compatibel_in_beschrijving_geen_replica(self):
        """'compatibel' alleen in beschrijving → niet als replica markeren."""
        flagged, _ = is_replica("LEGO Technic 42099", "Past in alle compatibele displays.")
        assert not flagged


class TestBundle:
    def test_vijf_sets_in_beschrijving(self):
        """Speed Champions bundel met 5 setnummers."""
        flagged, reason = is_bundle(
            "LEGO Speed Champions Collectie: 5 Nieuwe Sets!",
            "LEGO 76917: Nissan - LEGO 77256: Time Machine - LEGO 76924: Mercedes "
            "- LEGO 77237: Dodge - LEGO 77252: APXGP"
        )
        assert flagged, f"Verwacht bundel, reden: {reason!r}"

    def test_bundel_in_titel(self):
        flagged, _ = is_bundle("LEGO bundel 3 sets technic", "")
        assert flagged

    def test_collectie_in_titel(self):
        flagged, _ = is_bundle("LEGO Technic Collectie te koop", "")
        assert flagged

    def test_losse_set_niet_gebundeld(self):
        flagged, _ = is_bundle("LEGO Technic 42099 Lamborghini", "Originele LEGO set, sealed.")
        assert not flagged

    def test_twee_setnummers_geen_bundel(self):
        """2 setnummers in beschrijving is nog geen bundel (drempel is 3)."""
        flagged, _ = is_bundle("LEGO set", "Heb ook LEGO 42099 en LEGO 10305 te koop.")
        assert not flagged

    def test_drie_setnummers_wel_bundel(self):
        flagged, _ = is_bundle("LEGO sets", "LEGO 42099, LEGO 10305 en LEGO 75192 te koop")
        assert flagged


class TestAccessory:
    def test_led_kit(self):
        flagged, _ = is_accessory("LED kit voor LEGO 10295 Porsche")
        assert flagged

    def test_display_case(self):
        flagged, _ = is_accessory("Display case voor LEGO sets")
        assert flagged

    def test_normale_set_niet_geflagged(self):
        flagged, _ = is_accessory("LEGO Technic 42099 Lamborghini")
        assert not flagged

    def test_verlichting_in_beschrijving_geen_accessoire(self):
        """is_accessory checkt alleen titel."""
        flagged, _ = is_accessory("LEGO 42096 compleet")
        assert not flagged
