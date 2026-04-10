"""
Tests voor price intelligence berekeningen.
"""

import pytest
from src.analysis.price_intelligence import _iqr_filter, _percentile


class TestIQRFilter:
    def test_te_weinig_prijzen_geen_filter(self):
        prices = [100.0, 200.0, 300.0]
        assert _iqr_filter(prices) == prices

    def test_uitschieter_verwijderd(self):
        prices = [100.0, 105.0, 110.0, 108.0, 102.0, 500.0]  # 500 is uitschieter
        result = _iqr_filter(prices)
        assert 500.0 not in result
        assert len(result) == 5

    def test_identieke_prijzen_geen_filter(self):
        prices = [100.0, 100.0, 100.0, 100.0, 100.0]
        assert _iqr_filter(prices) == prices

    def test_normale_spreiding_ongewijzigd(self):
        prices = [90.0, 95.0, 100.0, 105.0, 110.0, 115.0]
        result = _iqr_filter(prices)
        assert len(result) == len(prices)  # geen outliers

    def test_lege_lijst(self):
        assert _iqr_filter([]) == []


class TestPercentile:
    def test_p50_mediaan(self):
        prices = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile(prices, 50) == 3.0

    def test_lege_lijst_geeft_none(self):
        assert _percentile([], 50) is None

    def test_enkele_waarde(self):
        assert _percentile([42.0], 50) == 42.0

    def test_p10_laag_einde(self):
        prices = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        p10 = _percentile(prices, 10)
        assert p10 < 20.0  # moet dicht bij het lage einde liggen
