"""Tests for the section labels (ingest/sections.py) and for re-indexing (ingest/embed_index.py).

NEW FILE (18 Nov 2026). Pages are short made-up texts; the index tests use an in-memory Qdrant and the
built-in fallback embedding, so nothing is downloaded.
"""
import pytest

from ingest.chunk import chunk_pages
from ingest.sections import _load_sections, assign_sections, headings_in, keep_keys

BODY = "\n".join(f"Ordinary sentence number {i} of the page, long enough not to be a heading at all." for i in range(15))


def page(n, heading=None, extra=""):
    return {"page": n, "text": (heading + "\n" if heading else "") + BODY + "\n" + extra}


def labels(pages, **kw):
    return [p["section"] for p in assign_sections(pages, **kw)]


def test_a_heading_must_start_the_line_or_be_most_of_it():
    specs = _load_sections()
    assert headings_in("Risk Management", specs) == ["risk"]
    assert headings_in("Notes to the standalone financial statements for the year ended 31st March, 2026", specs) == ["notes"]
    assert headings_in("Report of the Board of Directors and Management Discussion & Analysis", specs) == ["mdna"]
    assert headings_in("Chairman’s Statement", specs) == ["overview"]                       # curly apostrophe
    assert headings_in("We believe learning is a critical lever and review our risk management approach every year.", specs) == []
    assert headings_in("VALUE CREATION FOR STAKEHOLDERS   RISK MANAGEMENT   STATUTORY REPORTS AND FINANCIAL STATEMENTS", specs) == []   # a navigation bar


def test_a_mention_in_the_text_does_not_change_the_section():
    """The old rule labelled the CEO's statement 'risk' because an earlier page mentioned risk management."""
    pages = [page(1), page(2, extra="Our risk management framework is described later."), page(3, "CEO & MD's Statement"), page(4),
             page(5, "Management Discussion and Analysis"), page(6), page(7, "Risk Management"), page(8)]
    assert labels(pages) == ["overview", "overview", "overview", "overview", "mdna", "mdna", "risk", "risk"]
    assert "overview" in keep_keys()                                                         # early pages are indexed, not dropped


def test_contents_page_one_page_sections_and_short_sections():
    toc = {"page": 2, "text": "Contents\nManagement Discussion and Analysis\nCorporate Governance Report\nRisk Management\nNotes to the Financial Statements\n" + BODY}
    pages = [page(1, "Chairman's Statement"), toc, page(3), page(4, "Financial Highlights"), page(5)]
    assert labels(pages) == ["overview", "overview", "overview", "highlights", "overview"]   # highlights is one page only
    pages = [page(1, "Board's Report")] + [page(2, "Risk Management")] + [page(n) for n in range(3, 20)]
    got = labels(pages)
    assert got[1:13] == ["risk"] * 12 and set(got[13:]) == {"directors_report"}              # risk ends after 12 pages


def test_statement_pages_scope_and_notes():
    pages = [page(1, "Independent Auditor's Report"), page(2), page(3), page(4, "Notes to the standalone financial statements"),
             page(5, "Financial risk management"), page(6), page(7, "Corporate Governance Report")]
    out = assign_sections(pages, statement_pages={2: ("balance_sheet", "standalone"), 3: ("pnl", "standalone"), 6: ("balance_sheet", "consolidated")})
    assert [p["section"] for p in out] == ["auditor", "balance_sheet", "pnl", "notes", "notes", "balance_sheet", "governance"]
    assert [p["scope"] for p in out] == ["", "standalone", "standalone", "standalone", "standalone", "consolidated", ""]
    chunks = chunk_pages(out, {"company": "X", "ticker": "X", "fiscal_year": "2025-26", "scope": "consolidated", "pdf": "x.pdf"}, keep_sections=keep_keys())
    by_page = {c["page"]: c for c in chunks}
    assert by_page[2]["scope"] == "standalone" and "| standalone | balance_sheet | p2]" in by_page[2]["text"]
    assert by_page[7]["scope"] == "" and by_page[7]["section"] == "governance"
    assert len({c["id"] for c in chunks}) == len(chunks)


def test_reindexing_replaces_instead_of_doubling():
    pytest.importorskip("qdrant_client")
    from finsight.retrieval.qdrant_store import QdrantStore
    from ingest.embed_index import index_chunks
    store = QdrantStore(collection="reindex", location=":memory:")
    chunks = [{"id": f"{t}-2025-26-p{n}-0", "text": f"{t} page {n}", "ticker": t, "fiscal_year": "2025-26", "page": n} for t in ("INFY", "TCS") for n in (1, 2, 3)]
    assert index_chunks(chunks, store=store, replace="all") == 6 and store.count() == 6
    index_chunks(chunks, store=store)                                 # same chunks again: overwritten, not added
    assert store.count() == 6
    infy = [c for c in chunks if c["ticker"] == "INFY"][:2]           # Infosys re-ingested with one page fewer
    index_chunks(infy, store=store, replace="INFY")
    assert store.count() == 5
    index_chunks(chunks[:1], store=store, replace="all")              # a full run starts from an empty collection
    assert store.count() == 1
