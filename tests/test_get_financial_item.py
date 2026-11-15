# ORIGINAL PLACEHOLDER (kept):
# """Tests: figure lookup returns value/unit/page for (company, fy, statement, scope). TODO (Week 2)."""
# import pytest
#
# @pytest.mark.skip(reason="get_financial_item not implemented yet")
# def test_lookup_revenue():
#     ...
#
# IMPLEMENTED (agent layer, 13 Nov 2026): the placeholder test was skipped; these run on a small made-up store.
"""Tests for get_financial_item: canonical ids, scope, report choice, tolerant labels, occurrence, errors."""
import pytest

from finsight.tools.base import ToolError
from finsight.tools.get_financial_item import get_financial_item


def test_lookup_revenue(figure_store):
    r = get_financial_item("Infosys", "revenue_from_operations", "2025-26")
    assert (r["value"], r["unit"], r["page"], r["citation"]) == (1000.0, "crore", 287, "INFY-FY2526-p287")


def test_scope_selects_a_different_figure(figure_store):
    assert get_financial_item("INFY", "revenue_from_operations", "2025-26", scope="standalone")["value"] == 800.0


def test_prior_year_can_be_read_from_the_later_report(figure_store):
    own = get_financial_item("INFY", "revenue_from_operations", "2024-25")
    later = get_financial_item("INFY", "revenue_from_operations", "2024-25", from_report="2025-26")
    assert own["citation"] == "INFY-FY2425-p276" and later["citation"] == "INFY-FY2526-p287" and later["value"] == 900.0


def test_label_with_suffix_marker_or_dropped_letter(figure_store):
    assert get_financial_item("INFY", "other_income", "2025-26")["line_item"] == "Other income, net"
    assert get_financial_item("INFY", "net_profit", "2025-26")["value"] == 180.0            # "PROFIT FOR THE EAR"
    assert get_financial_item("SBI", "net_profit", "2025-26", scope="standalone")["value"] == 600000.0   # "III. Net Profit ..."


def test_occurrence_picks_non_current_then_current_borrowings(figure_store):
    assert get_financial_item("Wipro", "non_current_borrowings", "2025-26")["value"] == 40.0
    assert get_financial_item("Wipro", "current_borrowings", "2025-26")["value"] == 60.0


def test_free_text_still_works(figure_store):
    assert get_financial_item("Infosys", "total expenses", "2025-26")["value"] == 810.0


def test_errors(figure_store):
    for args in (("Reliance Industries", "net_profit", "2025-26"), ("Infosys", "net_profit", "2019-20"),
                 ("Infosys", "deposits", "2025-26")):
        with pytest.raises(ToolError):
            get_financial_item(*args)


# ---- added 15 Nov 2026: fixes found while closing the figure-store gaps ----
def _store(rows):
    import pandas as pd
    cols = ["company", "ticker", "fiscal_year", "statement_type", "scope", "line_item", "value", "unit", "page", "report_fy", "column"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


def _row(ticker, statement, label, value, page, scope="consolidated", unit="crore"):
    return (ticker, ticker, "2025-26", statement, scope, label, value, unit, page, "2025-26", "current")


def test_total_equity_does_not_match_total_equity_and_liabilities(monkeypatch):
    import finsight.tools.get_financial_item as gfi
    df = _store([_row("ITC", "balance_sheet", "TOTAL ASSETS", 900.0, 252), _row("ITC", "balance_sheet", "TOTAL EQUITY AND LIABILITIES", 900.0, 252),
                 _row("ITC", "pnl", "Total Income (I+II)", 50.0, 253)])
    monkeypatch.setattr(gfi, "_load_store", lambda: df)
    assert get_financial_item("ITC", "total_assets", "2025-26")["value"] == 900.0
    assert get_financial_item("ITC", "total_income", "2025-26")["value"] == 50.0           # "(I+II)" suffix still fine
    with pytest.raises(ToolError):
        get_financial_item("ITC", "total_equity", "2025-26")


def test_bank_total_rows(monkeypatch):
    """RBI-format statements print bare "Total" rows: 1st/2nd on the P&L, 1st on the balance sheet."""
    import finsight.tools.get_financial_item as gfi
    rows = [_row("SBIN", "balance_sheet", "Deposits", 600.0, 200, "standalone", "thousand"), _row("SBIN", "balance_sheet", "TOTAL", 1000.0, 200, "standalone", "thousand"),
            _row("SBIN", "balance_sheet", "Advances", 500.0, 200, "standalone", "thousand"), _row("SBIN", "balance_sheet", "TOTAL", 1000.0, 200, "standalone", "thousand"),
            _row("SBIN", "pnl", "Interest earned", 80.0, 201, "standalone", "thousand"), _row("SBIN", "pnl", "TOTAL", 100.0, 201, "standalone", "thousand"),
            _row("SBIN", "pnl", "Operating expenses", 30.0, 201, "standalone", "thousand"), _row("SBIN", "pnl", "TOTAL", 70.0, 201, "standalone", "thousand"),
            _row("SBIN", "balance_sheet", "Total assets", 77.0, 404, "standalone", "crore")]            # a note, far from the statements
    monkeypatch.setattr(gfi, "_load_store", lambda: _store(rows))
    look = lambda item: get_financial_item("SBI", item, "2025-26", scope="standalone")
    assert look("total_income")["value"] == 100.0 and look("total_expenses")["value"] == 70.0
    assert (look("total_assets")["value"], look("total_assets")["page"]) == (1000.0, 200)             # the statement, not the note
    monkeypatch.setattr(gfi, "_load_store", lambda: _store([_row("INFY", "pnl", "Total", 5.0, 10), _row("INFY", "balance_sheet", "Equity", 5.0, 9)]))
    with pytest.raises(ToolError):
        get_financial_item("Infosys", "total_income", "2025-26")                                       # banks only


def test_primary_statement_pages_win_over_an_earlier_look_alike_page(monkeypatch):
    """HDFC Bank FY2025-26: a page titled like a balance sheet at p417; the real statements are p471-473."""
    import finsight.tools.get_financial_item as gfi
    rows = [_row("HDFCBANK", "balance_sheet", "Deposits", 1.0, 417), _row("HDFCBANK", "balance_sheet", "Deposits", 3099638.29, 471),
            _row("HDFCBANK", "pnl", "Interest earned", 2.0, 472), _row("HDFCBANK", "cash_flow", "Net cash flow from operating activities", 3.0, 473)]
    df = _store(rows)
    assert gfi._primary_pages(df) == {"balance_sheet": {471}, "pnl": {472}, "cash_flow": {473}}
    monkeypatch.setattr(gfi, "_load_store", lambda: df)
    r = get_financial_item("HDFC Bank", "deposits", "2025-26")
    assert (r["value"], r["page"]) == (3099638.29, 471)
    assert gfi._primary_pages(_store(rows[:1])) == {}                                                  # one lone page: no restriction
