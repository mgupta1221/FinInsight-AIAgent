"""Links from a citation to the page of the report on the company's website.

NEW FILE (22 Nov 2026).

WHY: every answer cites a page, for example TCS-FY2526-p168, but the reader had to find the report and turn to
     the page by hand. data/report_sources.csv now holds the web address of each report, so the screen can
     offer a link that opens the report at that page (address + "#page=168"; Chrome and Edge open a PDF there).

How a citation is matched to a report: the ticker gives the company's `pdf_prefix` (config/companies.yaml), and
the file whose name starts with that prefix and contains the year is taken from report_sources.csv. This is the
same rule the ingestion uses to find the PDF.

The page number in a citation is the page of the PDF file, counted from 1, not the number printed on the page.
A report without an address in the file gets no link; nothing else changes.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from finsight.config import REPO_ROOT
from finsight.tools.get_company_profile import get_company_profile

CSV_PATH = REPO_ROOT / "data" / "report_sources.csv"
CITATION = re.compile(r"^([A-Z&]+)-FY(\d\d)(\d\d)-p(\d+)$")
_cache: dict = {}


def _rows(path: Path) -> list[dict]:
    """The rows of report_sources.csv; read again only when the file has changed."""
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    if _cache.get("key") != (str(path), stamp):
        with open(path, encoding="utf-8-sig", newline="") as f:
            _cache.update(key=(str(path), stamp), rows=list(csv.DictReader(f)))
    return _cache["rows"]


def page_link(citation: str, path: Path | None = None) -> str | None:
    """'TCS-FY2526-p168' -> 'https://.../report.pdf#page=168', or None if the report has no address."""
    m = CITATION.match((citation or "").strip())
    if not m:
        return None
    ticker, y1, y2, page = m.groups()
    try:
        prefix = get_company_profile(ticker)["pdf_prefix"]
    except Exception:  # noqa: BLE001  unknown ticker
        return None
    year = f"20{y1}-{y2}"
    for row in _rows(path or CSV_PATH):
        name, url = row.get("filename") or "", (row.get("url") or "").strip()
        if name.startswith(prefix + "-") and year in name and url.lower().startswith(("http://", "https://")):
            return f"{url.split('#')[0]}#page={page}"          # an address typed with its own "#page=2" is cleaned
    return None


def cited(a) -> list[str]:
    """Every citation of an answer, each once, in the order shown: sources, key points, figures."""
    out: list[str] = []
    for c in list(a.citations or []) + [k.citation for k in a.key_points or []] + [f.citation for f in a.inputs or []]:
        if c and c not in out:
            out.append(c)
    return out


def links_markdown(a, path: Path | None = None) -> str:
    """One line of links for an answer, or '' if none of its reports has an address."""
    links = [(c, page_link(c, path)) for c in cited(a)]
    links = [f"[{c}]({u})" for c, u in links if u]
    return ("**Open the cited page:** " + " · ".join(links)) if links else ""
