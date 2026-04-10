"""
Tests voor Marktplaats-specifieke filterlogica.
"""

import re
import pytest

# Importeer de regex direct uit de scraper
from src.scrapers.marktplaats_lego import _SET_NUMBER_RE, _looks_like_set_number


class TestWrongSetFilter:
    """Verifica de wrong_set logica: titel met ander setnummer → verwerp."""

    def _has_wrong_set(self, title: str, set_number: str) -> bool:
        """Simuleert de wrong_set check uit de scraper."""
        title_numbers = {
            n for n in _SET_NUMBER_RE.findall(title)
            if _looks_like_set_number(n)
        }
        return bool(title_numbers) and set_number not in title_numbers

    def test_speed_champions_bij_technic(self):
        """Speed Champions 76895 verschijnt in Technic 42099-zoekopdracht."""
        assert self._has_wrong_set("LEGO Speed Champions 76895 Ferrari 512", "42099")

    def test_correct_setnummer_geen_reject(self):
        assert not self._has_wrong_set("LEGO 42099 Lamborghini Sián compleet", "42099")

    def test_geen_setnummer_in_titel_geen_reject(self):
        """Naam-zoekopdracht: geen nummer in titel → geen wrong_set reject."""
        assert not self._has_wrong_set("LEGO Lamborghini compleet met doos", "42099")

    def test_jaarnummer_niet_als_setnummer(self):
        """'2024' is geen setnummer → niet als wrong_set beschouwd."""
        assert not self._has_wrong_set("LEGO Technic nieuw 2024", "42099")

    def test_beide_nummers_aanwezig_geen_reject(self):
        """Onze set én een ander nummer → onze set aanwezig, dus geen reject."""
        assert not self._has_wrong_set("LEGO 42099 + 10305 bundel", "42099")


class TestLooksLikeSetNumber:
    def test_jaarnummers_zijn_geen_setnummer(self):
        assert not _looks_like_set_number("2024")
        assert not _looks_like_set_number("2023")
        assert not _looks_like_set_number("2022")
        assert not _looks_like_set_number("1999")

    def test_echte_setnummers(self):
        assert _looks_like_set_number("42099")
        assert _looks_like_set_number("10305")
        assert _looks_like_set_number("75192")
        assert _looks_like_set_number("8880")
