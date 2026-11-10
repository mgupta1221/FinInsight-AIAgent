"""Tests for unit normalisation."""

import pytest

from finsight.tools.base import ToolError
from finsight.tools.normalise_units import normalise, to_common


def test_crore_to_million():
    # 1 crore = 10,000,000 = 10 million
    assert normalise(1, "crore", "million")["value"] == pytest.approx(10.0)


def test_lakh_to_crore():
    # 100 lakh = 1 crore
    assert normalise(100, "lakh", "crore")["value"] == pytest.approx(1.0)


def test_identity():
    assert normalise(42, "crore", "crore")["value"] == pytest.approx(42.0)


def test_case_and_alias_insensitive():
    assert normalise(1, "Cr", "Crore")["value"] == pytest.approx(1.0)


def test_unknown_unit_raises():
    with pytest.raises(ToolError):
        normalise(1, "furlong", "crore")


def test_to_common_mixed():
    vals = to_common([(1, "crore"), (10, "million"), (100, "lakh")], "crore")
    assert vals == pytest.approx([1.0, 1.0, 1.0])
