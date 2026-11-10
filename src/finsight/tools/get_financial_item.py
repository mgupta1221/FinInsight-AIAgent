"""Tool: get_financial_item — the primary source of numbers.

Queries the structured figure store (store/statement_lines.parquet) for a line item and returns its
value, unit, page, and a citation. Numbers in answers come from here (or a cited table), never from
the model. Raises ToolError if the store is missing or no matching row is found.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from finsight.config import settings
from finsight.tools.base import ToolError, register
from finsight.tools.get_company_profile import get_company_profile


@lru_cache(maxsize=1)
def _load_store() -> pd.DataFrame:
    path = settings.store_dir / "statement_lines.parquet"
    if not path.exists():
        raise ToolError(f"figure store not found ({path}); run ingestion first")
    return pd.read_parquet(path)


def _citation(ticker: str, fy: str, page: int) -> str:
    yy = fy.replace("-", "")[2:]  # 2024-25 -> 2425
    return f"{ticker}-FY{yy}-p{page}"


@register("get_financial_item")
def get_financial_item(
    company: str,
    line_item: str,
    fiscal_year: str,
    statement: str | None = None,
    scope: str = "consolidated",
) -> dict:
    """Return {value, unit, page, citation, line_item, matched} for a line item.

    `line_item` is matched case-insensitively as a substring (e.g. "revenue from operations").
    """
    prof = get_company_profile(company)  # raises if out of corpus
    df = _load_store()
    q = df[(df["ticker"] == prof["ticker"]) & (df["fiscal_year"] == fiscal_year)]
    if scope:
        q = q[q["scope"] == scope]
    if statement:
        q = q[q["statement_type"] == statement]
    needle = line_item.strip().lower()
    hits = q[q["line_item"].str.contains(needle, case=False, na=False, regex=False)]
    if hits.empty:
        raise ToolError(
            f"no figure for '{line_item}' ({prof['ticker']} FY{fiscal_year} {scope})"
        )
    # Prefer the shortest matching label (closest to the exact line item).
    row = hits.loc[hits["line_item"].str.len().idxmin()]
    return {
        "line_item": row["line_item"],
        "value": float(row["value"]),
        "unit": row["unit"],
        "page": int(row["page"]),
        "citation": _citation(prof["ticker"], fiscal_year, int(row["page"])),
        "matched": int(len(hits)),
    }
