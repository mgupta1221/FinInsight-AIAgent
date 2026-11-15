"""Tests for the figure extractor (ingest/statements.py): titles, scope, units and amount columns.

NEW FILE (15 Nov 2026). Each test is one layout problem found in the real annual reports. The tests use
short made-up lines, so they run without any PDF.
"""
import pytest

from ingest.statements import BIG_TITLE, classify, column_groups, despace, page_unit, scope_of, title_of


def line(y, *tokens):
    """A visual line: tokens are (right_edge_x, text). Returns the tuple layout lines_from_words produces."""
    return [(x - 6 * len(t), y, x, y + 8, t, y + 4) for x, t in tokens]


@pytest.mark.parametrize("text,unit", [
    ("` in ‘000s", "thousand"),                                               # ICICI: curly quote
    ("(C in ‘000)", "thousand"),                                              # HDFC: rupee sign read as "C"
    ("(J in million)", "million"),                                            # Nestle
    ("(All amounts in J million, unless otherwise stated)", "million"),
    ("(All amounts in H crores, unless otherwise stated)", "crore"),          # HUL
    ("(C in millions, except share and per share data, unless otherwise stated)", "million"),   # Wipro
    ("(In ` crore)", "crore"), ("(` in Thousands)", "thousand"), ("(000s omitted)", "thousand"), ("Rs. in lakhs", "lakh"),
    ("an increase in interest of 2,000 crore", None), ("profit in crore terms", None)])
def test_unit_is_read_even_when_the_rupee_sign_is_lost(text, unit):
    assert page_unit(text) == unit


def test_titles():
    assert title_of("statements of profit and loss") == "pnl"                                  # Wipro: plural
    assert title_of("statements of cash flows") == "cash_flow"
    assert title_of("s ta n d a l o n e b a l a n c e s h e e t") == "balance_sheet"           # HDFC: letter-spaced
    assert title_of("consolidated balance sheet and profit and loss account") is None          # Kotak: running header
    assert title_of("consolidated profit and loss account") == "pnl"
    assert title_of("a summary of the cash flows statement is given below:") is None           # HCL board report
    assert title_of("k e y b a l a n c e s h e e t p a r a m e t e r s") is None               # not exactly the title
    assert despace("consolidated balance sheet") == ""                                         # normal text is left alone


def test_sideways_heading_must_be_exactly_the_statement_name():
    assert BIG_TITLE.match("consolidated statements of cash flows") and BIG_TITLE.match("balance sheet")
    assert not BIG_TITLE.match("balance sheet strength") and not BIG_TITLE.match("our balance sheet")


def test_scope_comes_from_the_page_then_from_the_auditors_report():
    assert scope_of("consolidated balance sheet", "standalone") == "consolidated"
    assert scope_of("s ta n d a l o n e b a l a n c e s h e e t", "consolidated") == "standalone"
    assert scope_of("balance sheet as at 31st march, 2026", "consolidated") == "consolidated"  # Nestle
    assert scope_of("balance sheet", None) == "standalone"


def test_classify_page():
    kotak_pnl = [line(20, (300, "Consolidated Balance Sheet and Profit and Loss Account")),
                 line(40, (200, "Consolidated Profit and Loss Account")), line(60, (200, "(H in thousands)"))]
    assert classify(kotak_pnl, 800) == ("pnl", "consolidated")
    bare = [line(20, (200, "Balance Sheet")), line(40, (200, "as at 31 March 2026"))]
    assert classify(bare, 800) is None                              # no scope stated, no auditor's report yet
    assert classify(bare, 800, "consolidated") == ("balance_sheet", "consolidated")
    margin = [line(20, (200, "(I in millions, except share data)"))]
    assert classify(margin, 800, "standalone", [("statements of profit and loss", True)]) == ("pnl", "standalone")
    assert classify(margin, 800, "standalone", [("statements of profit and loss", False)]) is None   # not sideways
    kpi = [line(20, (300, "K E Y P E R F O R M A N C E I N D I C AT O R S")), line(40, (200, "Standalone Balance Sheet"))]
    assert classify(kpi, 800, "standalone") is None


def test_two_plain_columns_are_current_and_prior_year():
    rows = [line(100 + 10 * i, (120, "Item"), (400, f"{1000 + i:,}"), (480, f"{900 + i:,}")) for i in range(8)]
    assert [len(g) for g in column_groups(rows)] == [1, 1]
    assert column_groups(rows)[0][0] == pytest.approx(400) and column_groups(rows)[1][0] == pytest.approx(480)


def test_three_columns_per_year_are_grouped_by_year():
    """ITC balance sheet: item amount, sub-total and total columns for each year."""
    rows = []
    for i in range(6):
        rows.append(line(100 + 20 * i, (120, "Item"), (300, f"{1000 + i:,}"), (440, f"{900 + i:,}")))            # inner
        rows.append(line(110 + 20 * i, (120, "Item"), (350, f"{2000 + i:,}"), (490, f"{1900 + i:,}")))           # middle
    rows += [line(300 + 10 * i, (120, "Total"), (350, "3,000"), (400, f"{5000 + i:,}"), (490, "2,900"), (540, f"{4900 + i:,}")) for i in range(5)]
    groups = column_groups(rows)
    assert [len(g) for g in groups] == [3, 3]
    assert max(groups[0]) < min(groups[1])                          # left half = current year, right half = prior


def test_four_filled_columns_keep_the_old_rule():
    """Standalone and consolidated side by side: every row fills all four columns -> use the last two."""
    rows = [line(100 + 10 * i, (120, "Item"), (300, "1,000"), (360, "1,100"), (420, "2,000"), (480, "2,100")) for i in range(8)]
    groups = column_groups(rows)
    assert [len(g) for g in groups] == [1, 1] and groups[0][0] == pytest.approx(420)
