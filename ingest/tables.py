"""Extract primary-statement line items into the structured figure store.

Week-1 baseline: a text-based extractor that scans the primary-statement pages (P&L, balance sheet,
cash flow) and captures rows of "<line item>  <current-year number>  [<prior-year number>]". It
produces rows of {company, ticker, fiscal_year, statement_type, scope, line_item, value, unit, page}
for store/statement_lines.parquet, which get_financial_item queries.

This is deliberately conservative (it is the single biggest accuracy lever, per the plan). Week-2
upgrades it with Docling/Camelot table structure + a 20-table hand-check. Numbers for gold answers
must come from here, never from chart OCR.
"""

from __future__ import annotations

import re

_PRIMARY = {"pnl", "balance_sheet", "cash_flow"}
# A label (letters/&/-/spaces) followed by at least one Indian-formatted number.
_NUM = r"\(?-?[\d,]+(?:\.\d+)?\)?"
_ROW_RE = re.compile(rf"^\s*([A-Za-z][A-Za-z &/,\-\(\)\.]+?)\s+({_NUM})(?:\s+({_NUM}))?\s*$")


def _to_float(tok: str) -> float | None:
    neg = tok.strip().startswith("(")
    cleaned = tok.replace(",", "").strip("()").strip()
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return -val if neg else val


def extract_statement_lines(pages: list[dict], meta: dict) -> list[dict]:
    """pages: [{page, text, section}] (sectioned); meta: {company, ticker, fiscal_year, scope, unit}."""
    rows: list[dict] = []
    unit = meta.get("unit", "crore")
    for pg in pages:
        if pg.get("section") not in _PRIMARY:
            continue
        for line in pg["text"].splitlines():
            m = _ROW_RE.match(line)
            if not m:
                continue
            label = re.sub(r"\s+", " ", m.group(1)).strip().lower()
            value = _to_float(m.group(2))
            if value is None or len(label) < 3:
                continue
            rows.append(
                {
                    "company": meta["company"],
                    "ticker": meta["ticker"],
                    "fiscal_year": meta["fiscal_year"],
                    "statement_type": pg["section"],
                    "scope": meta.get("scope", ""),
                    "line_item": label,
                    "value": value,
                    "unit": unit,
                    "page": pg["page"],
                }
            )
    return rows
