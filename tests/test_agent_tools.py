"""Tests for the tools and helpers added with the agent layer.

NEW FILE (agent layer, 13 Nov 2026): compare_rank, create_note_draft, company matching, the new glossary
sections, and the fiscal-year helpers.
"""
import pytest

from finsight.corpus import citation, fiscal_years, normalise_fy, previous_year, years_in
from finsight.tools.base import ToolError
from finsight.tools.calculate import evaluate_expression
from finsight.tools.company_match import find_companies, resolve_ticker
from finsight.tools.compare_rank import compare_rank
from finsight.tools.glossary import derived_inputs, get_metric, line_items, not_for_banks, reported_metrics


def test_compare_rank():
    out = compare_rank({"A": 3.0, "B": 1.0, "C": 2.0}, order="lowest")
    assert [r["name"] for r in out["ranking"]] == ["B", "C", "A"] and out["winner"] == "B"
    assert compare_rank({"A": 1.0, "B": 1.0})["tie"] is True
    with pytest.raises(ToolError):
        compare_rank({"A": 1.0, "B": None})


def test_create_note_draft_needs_a_verified_answer(tmp_path, monkeypatch):
    import finsight.tools.create_note_draft as nd
    monkeypatch.setattr(nd, "NOTES_DIR", tmp_path)
    with pytest.raises(ToolError):
        nd.create_note_draft("x", {"verified": False})
    out = nd.create_note_draft("Infosys revenue", {"verified": True, "answer": "Revenue was 1.", "citations": ["INFY-FY2526-p287"]})
    text = open(out["path"], encoding="utf-8").read()
    assert out["needs_approval"] and "DRAFT" in out["path"] and "Not investment advice" in text


def test_company_matching():
    assert resolve_ticker("Axis Bank") == "AXISBANK" and resolve_ticker("kotak") == "KOTAKBANK"
    assert resolve_ticker("Reliance Industries") is None
    assert find_companies("Which of SBI, ICICI Bank and HDFC Bank had the lowest GNPA?") == ["SBIN", "ICICIBANK", "HDFCBANK"]


def test_fiscal_year_helpers():
    assert fiscal_years() == ["2024-25", "2025-26"] and previous_year("2025-26") == "2024-25"
    assert normalise_fy("FY26") == "2025-26" and years_in("fy26 vs FY2024-25") == ["2025-26", "2024-25"]
    assert citation("INFY", "2025-26", 214) == "INFY-FY2526-p214"
    # added 15 Nov 2026: short forms typed in follow-up questions
    assert years_in("and for 25-26") == ["2025-26"] and years_in("FY24-25 vs 2025-2026") == ["2024-25", "2025-26"]
    assert years_in("2024/25") == ["2024-25"] and years_in("FY2025-26 and FY 2025") == ["2025-26", "2024-25"]
    assert years_in("see pages 24-30 and note 12-14") == [] and years_in("revenue in 2025-27") == []


def test_every_formula_input_can_be_fetched_or_derived():
    """Each computed metric's inputs must be statement lines or derived inputs, except those looked up as reported."""
    known = set(line_items()) | set(derived_inputs()) | {"current", "previous"}
    for metric in ("operating_margin", "ebitda_margin", "net_profit_margin", "debt_to_equity", "current_ratio",
                   "return_on_equity", "return_on_capital_employed"):
        assert set(get_metric(metric, False)["inputs"]) <= known, metric
    assert set(get_metric("cost_to_income", True)["inputs"]) <= known
    for spec in derived_inputs().values():
        assert set(spec["inputs"]) <= set(line_items())
        evaluate_expression(spec["formula"], {k: 1.0 for k in spec["inputs"]})


def test_reported_and_bank_rules():
    assert {"gross_npa_ratio", "casa_ratio", "net_interest_margin", "crar"} <= set(reported_metrics())
    assert "operating_margin" in not_for_banks() and "debt_to_equity" in not_for_banks()
