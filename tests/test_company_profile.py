"""Tests for get_company_profile + glossary loading."""

import pytest

from finsight.tools.base import ToolError
from finsight.tools.get_company_profile import get_company_profile, in_corpus
from finsight.tools.glossary import get_metric, list_metrics


def test_lookup_by_ticker():
    p = get_company_profile("INFY")
    assert p["sector"] == "it_services"
    assert p["is_bank"] is False
    assert p["fy_end"] == "03-31"


def test_lookup_by_name_variant():
    p = get_company_profile("HDFC Bank")
    assert p["is_bank"] is True
    assert p["ticker"] == "HDFCBANK"


def test_out_of_corpus_raises():
    with pytest.raises(ToolError):
        get_company_profile("Reliance Industries")
    assert in_corpus("Reliance Industries") is False


def test_glossary_bank_vs_non_bank():
    assert "gross_npa_ratio" in list_metrics(is_bank=True)
    assert "operating_margin" in list_metrics(is_bank=False)
    spec = get_metric("casa_ratio", is_bank=True)
    assert spec["unit"] == "percent"
