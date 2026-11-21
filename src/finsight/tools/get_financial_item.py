"""Tool: get_financial_item — the primary source of numbers.

Queries the structured figure store (store/statement_lines.parquet) for a line item and returns its
value, unit, page, and a citation. Numbers in answers come from here (or a cited table), never from
the model. Raises ToolError if the store is missing or no matching row is found.
"""

from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd

from finsight.config import settings
from finsight.tools.base import ToolError, register
from finsight.tools.get_company_profile import get_company_profile


@lru_cache(maxsize=1)
def _load_store() -> pd.DataFrame:
    path = settings.store_dir / "statement_lines.parquet"
    # OLD (kept):
    # if not path.exists():
    #     raise ToolError(f"figure store not found ({path}); run ingestion first")
    # return pd.read_parquet(path)
    # NEW (14 Nov 2026): fall back to a CSV copy of the same table (store/statement_lines.csv).
    # WHY: reading parquet needs the `pyarrow` package. On laptops with Windows Application Control
    # (Device Guard) the pyarrow DLLs are blocked ("An Application Control policy has blocked this file"),
    # so parquet cannot be read at all. CSV needs only pandas. Parquet is still used first when it works.
    csv_path = settings.store_dir / "statement_lines.csv"
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception:  # noqa: BLE001  pyarrow missing or blocked -> try the CSV copy
            if not csv_path.exists():
                raise
    if csv_path.exists():
        # keep fiscal years such as "2025-26" as text; pandas would otherwise leave them alone, but be explicit
        return pd.read_csv(csv_path, dtype={"fiscal_year": str, "report_fy": str, "ticker": str, "unit": str})
    raise ToolError(f"figure store not found ({path}); run ingestion first")


def _citation(ticker: str, fy: str, page: int) -> str:
    yy = fy.replace("-", "")[2:]  # 2024-25 -> 2425
    return f"{ticker}-FY{yy}-p{page}"


# =====================================================================================================
# CHANGED (agent layer, 13 Nov 2026). The original function is kept below, commented out.
#
# WHY it was changed
#   1. The original matched `line_item` as free text and returned the SHORTEST label containing it.
#      "revenue" could match "other operating revenue", and there was no way to say which statement line
#      was meant. The agent now passes a canonical id (e.g. "net_profit") defined in the `line_items`
#      section of config/glossary.yaml, which lists the exact label wordings used in the reports.
#   2. The figure store now has two extra columns, `report_fy` and `column` (see ingest/statements.py).
#      A year-on-year answer must read BOTH years from the later report (SPEC section 4, restated figures),
#      so the caller can pass `from_report`.
#   3. Labels in some PDFs lose letters ("PROFIT FOR THE EAR", "TOTAL EQ UITY"); a tolerant match handles it.
#   4. When the same label appears on several pages (statement, then notes), the first page is the statement.
#
# WHAT stays the same
#   The function name, the registry name, the first five parameters and the returned keys
#   (line_item, value, unit, page, citation, matched) are unchanged, so existing callers keep working.
#   Free text that is not a canonical id still works (old behaviour, on current-year rows).
# =====================================================================================================
# OLD: _MARKER = re.compile(r"^(\(?[ivxlc]+[.)]?|\(?[a-z]\)|\d+[.)]?)\s+")
# NEW (19 Nov 2026): a single letter in front of a label is a list marker too ("E PROFIT BEFORE EXCEPTIONAL ITEMS
# AND TAX", "G PROFIT BEFORE TAX"). WHY: Nestle letters its rows A, B, C ...; only the letters that also happen to be
# Roman numerals (C, I) were removed, so Nestle's profit before tax was "not found" and its operating margin failed.
_MARKER = re.compile(r"^(\(?[ivxlc]+[.)]?|\(?[a-z]\)|[a-z][.)]?|\d+[.)]?)\s+")


def _clean(label: str) -> str:
    """Lower-case label without list markers ("III.", "(a)") or a trailing "(I+II)"."""
    out = label.lower().strip()
    for _ in range(2):
        out = _MARKER.sub("", out)
    return re.sub(r"\s*\(.*$", "", out).strip(" .:")


def _key(text: str) -> str:
    """Letters only, without 'y': tolerates PDFs that drop or split letters in capitals."""
    return re.sub(r"[^a-z]", "", text.lower()).replace("y", "")


def _primary_pages(rows: pd.DataFrame) -> dict[str, set[int]]:
    """Pages of the primary statements of ONE report and scope: {statement_type: {pages}}.

    NEW (15 Nov 2026). The balance sheet, the P&L and (often) the cash-flow statement are printed on
    neighbouring pages. Pages no more than 10 apart are grouped into a block; the block holding the most
    different statements (at least two) is the set of primary statements. A statement type that is not in
    that block (SBI prints its cash flow 80 pages later) is not restricted: every page of it is searched.
    """
    pages = sorted({(int(p), s) for p, s in zip(rows["page"], rows["statement_type"])})
    blocks: list[list[tuple[int, str]]] = []
    for item in pages:
        # CHANGED (17 Nov 2026): pages up to 10 apart belong to one block.  OLD: <= 3
        # WHY: banks print the balance sheet, then several pages of schedules, then the P&L (SBI: p200 and
        #      p209). With a gap of 3 the real balance sheet fell outside the block and a later look-alike
        #      page was preferred. Stray pages that carry a statement title sit 40+ pages away, so 10 is safe.
        if blocks and item[0] - blocks[-1][-1][0] <= 10:
            blocks[-1].append(item)
        else:
            blocks.append([item])
    best = max(blocks, key=lambda b: len({s for _, s in b}), default=[])      # max() keeps the earliest on a tie
    if len({s for _, s in best}) < 2:
        return {}
    out: dict[str, set[int]] = {}
    for page, s in best:
        out.setdefault(s, set()).add(page)
    return out


@register("get_financial_item")
def get_financial_item(
    company: str,
    line_item: str,
    fiscal_year: str,
    statement: str | None = None,
    scope: str = "consolidated",
    from_report: str | None = None,
) -> dict:
    """Return one statement figure with its provenance.

    line_item   : a canonical id from glossary.yaml `line_items` (preferred), or free text (old behaviour).
    fiscal_year : the year of the VALUE, e.g. "2025-26".
    from_report : which annual report to read. Default: the report of `fiscal_year` itself; if that report
                  is not in the corpus, the next year's report (its prior-year column).

    Returns {line_item, value, unit, page, citation, matched, item, company, fiscal_year, scope, report_fy}.
    Raises ToolError if the company is out of corpus or no matching row exists.
    """
    from finsight.corpus import citation, fiscal_years, previous_year
    from finsight.tools.glossary import line_items

    prof = get_company_profile(company)  # raises if out of corpus
    df = _load_store()
    if "report_fy" not in df.columns:
        raise ToolError("the figure store was built by the old extractor; run `python -m ingest.run_ingest --figures-only`")
    years = fiscal_years()
    report = from_report or (fiscal_year if fiscal_year in years else
                             next((y for y in years if previous_year(y) == fiscal_year), None))
    if report not in years:
        raise ToolError(f"fiscal year {fiscal_year} is not in the corpus")

    q = df[(df["ticker"] == prof["ticker"]) & (df["report_fy"] == report) & (df["fiscal_year"] == fiscal_year)]
    if scope:
        q = q[q["scope"] == scope]
    spec = line_items().get(line_item)
    if spec is not None:
        # NEW (15 Nov 2026): look only at the pages of the primary statements, when they can be identified.
        # OLD: q = q[q["statement_type"] == (statement or spec["statement"])]      (all pages of that type)
        # WHY: some pages BEFORE the real statements also carry a statement title (HDFC Bank FY2025-26 has a
        #      page titled like a consolidated balance sheet at p417; the real one is p471). The rule "first
        #      page wins" then read the wrong page. See _primary_pages below.
        wanted = statement or spec["statement"]
        primary = _primary_pages(q).get(wanted)
        q = q[q["statement_type"] == wanted]
        if primary:
            q = q[q["page"].isin(primary)]
        cleaned = q["line_item"].map(_clean)
        # NEW (19 Nov 2026): a company name fused to the front of a label is dropped ("WIPRO TOTAL EQUITY").
        # WHY: on Wipro's balance sheet a page-header word runs into the row, so "total equity" was not found
        #      and the debt-to-equity ratio failed.
        own = {prof["ticker"].lower(), str(prof["name"]).split()[0].lower(), "integrated"}
        cleaned = cleaned.map(lambda c: c.split(" ", 1)[1] if " " in c and c.split(" ", 1)[0] in own else c)
        labels = list(spec["labels"])
        hits = q[cleaned.isin(labels)]
        if hits.empty:
            hits = q[cleaned.map(_key).isin({_key(l) for l in labels})]
        if hits.empty:
            # CHANGED (15 Nov 2026).  OLD: rx = re.compile("|".join(re.escape(l) + r"(?![a-z])" for l in labels))
            # WHY: "total equity" matched the row "TOTAL EQUITY AND LIABILITIES" (ITC, Wipro), so total assets
            #      was returned as total equity. A label followed by "and ..." / "& ..." is a different row.
            # CHANGED again (17 Nov 2026): "of ..." and "before ..." continuations are rejected too.
            # OLD (15 Nov): rx = re.compile("|".join(re.escape(l) + r"(?![a-z])(?!\s+(and|&)\s)" for l in labels))
            # WHY: "deposits" matched "Deposits of branches outside India" (a part of the figure, on a schedule
            #      page), "tax expense" matched "Tax expense of discontinued operations" (ITC), and "net profit
            #      for the year" matched "... before deducting minority interest" (ICICI). Each is a different
            #      row from the one asked for. Not finding a figure is safer than returning a neighbour.
            #      The LONGEST label that starts the row decides: "net profit for the year before ..." is judged
            #      as "net profit for the year" + " before ...", not as "net profit" + " for the year ...".
            # (15 Nov version, kept): rx = re.compile("|".join(re.escape(l) + r"(?![a-z])(?!\s+(and|&|of|before)\s)" for l in labels))
            #                         hits = q[cleaned.map(lambda c: bool(rx.match(c)))]
            by_length = sorted(labels, key=len, reverse=True)

            def _starts_with_label(c: str) -> bool:
                label = next((l for l in by_length if c.startswith(l)), None)
                if label is None:
                    return False
                rest = c[len(label):]
                return not re.match(r"[a-z]", rest) and not re.match(r"\s+(and|&|of|before)\s", rest)

            hits = q[cleaned.map(_starts_with_label)]
        if not hits.empty:
            hits = hits[hits["page"] == hits["page"].min()]          # the statement itself, not later notes
        idx = int(spec.get("occurrence", 0))
        # NEW (15 Nov 2026): bank fallback labels (see the note above total_income in config/glossary.yaml).
        # WHY: SBI, HDFC Bank and Kotak print total income, total expenditure and total assets as a bare
        #      "Total" row, so the normal labels found nothing. Only the statement's FIRST page is used,
        #      because schedules on later pages have "Total" rows of their own.
        #      The fallback is also used when the normal label was found only on a LATER page (a note or a
        #      segment table), so that the answer cites the statement itself.
        if prof.get("is_bank") and spec.get("bank_labels") and not q.empty:
            first_page = q[q["page"] == q["page"].min()]
            if hits.empty or hits["page"].min() != q["page"].min():
                bank_hits = first_page[first_page["line_item"].map(_clean).isin(list(spec["bank_labels"]))]
                if int(spec.get("bank_occurrence", 0)) < len(bank_hits):
                    hits, idx = bank_hits, int(spec.get("bank_occurrence", 0))
        if hits.empty or idx >= len(hits):
            raise ToolError(f"no figure for '{line_item}' ({prof['ticker']} FY{fiscal_year} {scope}, FY{report} report)")
        row = hits.iloc[idx]
    else:                                                            # free text: the original behaviour
        if statement:
            q = q[q["statement_type"] == statement]
        hits = q[q["line_item"].str.contains(line_item.strip(), case=False, na=False, regex=False)]
        if hits.empty:
            raise ToolError(f"no figure for '{line_item}' ({prof['ticker']} FY{fiscal_year} {scope})")
        row = hits.loc[hits["line_item"].str.len().idxmin()]
    page = int(row["page"])
    return {
        "line_item": row["line_item"],
        "value": float(row["value"]),
        "unit": row["unit"],
        "page": page,
        "citation": citation(prof["ticker"], report, page),
        "matched": int(len(hits)),
        "item": line_item,
        "company": prof["ticker"],
        "fiscal_year": fiscal_year,
        "scope": scope,
        "report_fy": report,
    }


# ----------------------------- ORIGINAL IMPLEMENTATION (kept for reference) -----------------------------
# @register("get_financial_item")
# def get_financial_item(
#     company: str,
#     line_item: str,
#     fiscal_year: str,
#     statement: str | None = None,
#     scope: str = "consolidated",
# ) -> dict:
#     """Return {value, unit, page, citation, line_item, matched} for a line item.
#
#     `line_item` is matched case-insensitively as a substring (e.g. "revenue from operations").
#     """
#     prof = get_company_profile(company)  # raises if out of corpus
#     df = _load_store()
#     q = df[(df["ticker"] == prof["ticker"]) & (df["fiscal_year"] == fiscal_year)]
#     if scope:
#         q = q[q["scope"] == scope]
#     if statement:
#         q = q[q["statement_type"] == statement]
#     needle = line_item.strip().lower()
#     hits = q[q["line_item"].str.contains(needle, case=False, na=False, regex=False)]
#     if hits.empty:
#         raise ToolError(
#             f"no figure for '{line_item}' ({prof['ticker']} FY{fiscal_year} {scope})"
#         )
#     # Prefer the shortest matching label (closest to the exact line item).
#     row = hits.loc[hits["line_item"].str.len().idxmin()]
#     return {
#         "line_item": row["line_item"],
#         "value": float(row["value"]),
#         "unit": row["unit"],
#         "page": int(row["page"]),
#         "citation": _citation(prof["ticker"], fiscal_year, int(row["page"])),
#         "matched": int(len(hits)),
#     }
