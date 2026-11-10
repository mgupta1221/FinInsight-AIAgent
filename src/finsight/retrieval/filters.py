"""Build Qdrant payload filters. Always filter by company/year/statement BEFORE ranking so the
retriever never returns the right company's wrong year (the reports look near-identical)."""
from __future__ import annotations


def build_filter(company=None, fiscal_year=None, statement=None, scope=None, section=None) -> dict:
    flt = {
        "ticker": company,
        "fiscal_year": fiscal_year,
        "statement": statement,
        "scope": scope,
        "section": section,
    }
    return {k: v for k, v in flt.items() if v is not None}
