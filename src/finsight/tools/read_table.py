"""Tool: read_table — return the content of a specific cited page.

Given a company, fiscal year, and page number, returns that page's text (so the model/user can read a
whole table and pick a row). Capped at ~40 rows per the spec. Week-1 uses the parsed page text from
data/parsed; Week-2 can return the structured table markdown from Docling/Camelot.
"""

from __future__ import annotations

from finsight.tools.base import ToolError, register
from finsight.tools.get_company_profile import get_company_profile
from ingest.parse import parse_pdf
from finsight.config import settings

MAX_ROWS = 40
PDF_DIR = settings.data_dir / "manual-collection"


@register("read_table")
def read_table(company: str, fiscal_year: str, page: int) -> dict:
    """Return {company, fiscal_year, page, rows[]} for a cited page (≤40 rows)."""
    prof = get_company_profile(company)
    matches = list(PDF_DIR.glob(f"{prof['pdf_prefix']}*{fiscal_year}*.pdf"))
    if not matches:
        raise ToolError(f"report PDF not found for {prof['ticker']} FY{fiscal_year}")
    pages = parse_pdf(matches[0])
    if page < 1 or page > len(pages):
        raise ToolError(f"page {page} out of range (1..{len(pages)})")
    rows = [ln for ln in pages[page - 1]["text"].splitlines() if ln.strip()][:MAX_ROWS]
    return {"company": prof["name"], "fiscal_year": fiscal_year, "page": page, "rows": rows}
