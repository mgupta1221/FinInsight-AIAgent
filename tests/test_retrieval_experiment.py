"""Tests for eval/retrieval_experiment.py (the search-mode comparison).

NEW FILE (18 Nov 2026). The search itself is replaced by a scripted one, so no index is needed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
import retrieval_experiment as rx  # noqa: E402

CASES = [{"id": "fact-001", "query": "Infosys revenue", "ticker": "INFY", "fiscal_year": "2025-26", "page": 287},
         {"id": "fact-002", "query": "TCS net profit", "ticker": "TCS", "fiscal_year": "2024-25", "page": 181}]


def hit(ticker, fy, page):
    return {"ticker": ticker, "fiscal_year": fy, "page": page, "text": "x", "id": f"{ticker}-{fy}-{page}"}


def test_found_at_needs_company_year_and_page():
    hits = [hit("TCS", "2025-26", 287), hit("INFY", "2024-25", 287), hit("INFY", "2025-26", 287)]
    assert rx.found_at(hits, CASES[0]) == 3 and rx.found_at(hits[:2], CASES[0]) is None


def test_recall_table():
    def scripted(mode, query, flt, store):
        if mode == "bm25":                                   # right page first, but only with the filter
            return [hit("INFY", "2025-26", 287), hit("TCS", "2024-25", 181)] if flt else [hit("WIPRO", "2025-26", 1)]
        if mode == "dense":                                  # right page at rank 4
            return [hit("X", "2025-26", n) for n in (1, 2, 3)] + [hit("INFY", "2025-26", 287), hit("TCS", "2024-25", 181)]
        return [hit("INFY", "2025-26", 287)]                 # finds Infosys only
    rows = {(r["mode"], r["company_year_filter"]): r for r in rx.run(CASES, modes=("bm25", "dense", "hybrid"), searcher=scripted)}
    assert rows[("bm25", "yes")]["recall@1"] == 0.5 and rows[("bm25", "yes")]["recall@3"] == 1.0
    assert rows[("bm25", "no")]["recall@10"] == 0.0
    assert rows[("dense", "yes")]["recall@3"] == 0.0 and rows[("dense", "yes")]["recall@5"] == 1.0
    assert rows[("hybrid", "no")]["recall@1"] == 0.5 and rows[("hybrid", "no")]["cases"] == 2


def test_cases_from_a_filled_workbook(tmp_path):
    pytest.importorskip("openpyxl")
    import make_gold_workbook as mg
    from openpyxl import load_workbook
    qs = [{"id": "fact-001", "type": "fact", "question": "What was Infosys' consolidated revenue from operations in FY2025-26?", "company": "INFY",
           "fiscal_year": "2025-26", "statement": "consolidated", "metric": None, "gold": None, "gold_status": "pending_verification"}]
    book = tmp_path / "gold.xlsx"
    mg.build(book, questions=qs, hints=False)
    assert rx.cases_from_workbook(book) == []                                       # nothing typed in yet
    wb = load_workbook(book)
    ws = wb["Inputs"]
    col = {c.value: c.column for c in ws[1]}
    ws.cell(2, col["page_author"], 287)
    ws.cell(2, col["page_verifier"], 288)
    wb.save(book)
    assert rx.cases_from_workbook(book) == [{"id": "fact-001", "query": qs[0]["question"], "ticker": "INFY", "fiscal_year": "2025-26", "page": 287}]
    assert rx.cases_from_workbook(book, verified=True) == []                        # the verifier's page differs
    qs.append({"id": "summary-001", "type": "summary", "question": "Summarise the top risks ITC lists in its FY2025-26 report.", "company": "ITC",
               "fiscal_year": "2025-26", "statement": None, "metric": None, "gold": None, "gold_status": "pending_verification"})
    mg.build(book, questions=qs, hints=False)
    wb = load_workbook(book)
    kp = wb["KeyPoints"]
    for c, v in zip(range(3, 7), ("Cyber risk", 110, "Asha", None)):
        kp.cell(2, c, v)
    wb.save(book)
    assert rx.cases_from_workbook(book) == [{"id": "summary-001", "query": qs[1]["question"], "ticker": "ITC", "fiscal_year": "2025-26", "page": 110}]
    assert rx.cases_from_workbook(book, verified=True) == []                        # key point not verified yet
