"""Tests for the calculator + glossary: formulas compute correctly and unsafe input is rejected."""

import pytest

from finsight.tools.base import ToolError
from finsight.tools.calculate import calculate, evaluate_expression


def test_operating_margin_non_bank():
    r = calculate("operating_margin", {"ebit": 250.0, "revenue_from_operations": 1000.0})
    assert r["value"] == pytest.approx(25.0)
    assert r["unit"] == "percent"
    assert "ebit" in r["formula"]


def test_yoy_change():
    r = calculate("yoy_change", {"current": 120.0, "previous": 100.0})
    assert r["value"] == pytest.approx(20.0)


def test_bank_gnpa_ratio():
    r = calculate("gross_npa_ratio", {"gross_npa": 50.0, "gross_advances": 2000.0}, is_bank=True)
    assert r["value"] == pytest.approx(2.5)


def test_missing_input_raises():
    with pytest.raises(ToolError):
        calculate("operating_margin", {"ebit": 10.0})


def test_unknown_metric_raises():
    with pytest.raises(ToolError):
        calculate("made_up_metric", {"a": 1})


def test_division_by_zero_raises():
    with pytest.raises(ToolError):
        calculate("operating_margin", {"ebit": 10.0, "revenue_from_operations": 0.0})


def test_safe_evaluator_blocks_code():
    with pytest.raises(ToolError):
        evaluate_expression("__import__('os').system('echo hi')", {})
