"""Find corpus companies inside free text.

NEW FILE (agent layer, 13 Nov 2026).

WHY: get_company_profile() answers "is this ONE name in the corpus?". The planner needs a different
question answered: "which corpus companies does this SENTENCE mention, and in what order?" (for example
"Which of SBI, ICICI Bank and HDFC Bank had the lowest gross NPA ratio?"). This module does that using the
company names, tickers, pdf prefixes and the new `aliases` lists in config/companies.yaml. It is also the
planner's safety net when the model returns no company or a wrong one.
"""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from finsight.config import settings


@lru_cache(maxsize=1)
def _aliases() -> dict[str, list[str]]:
    with open(settings.config_dir / "companies.yaml", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    out: dict[str, list[str]] = {}
    for c in data.get("companies", []):
        names = [c.get("name", ""), c.get("ticker", ""), c.get("pdf_prefix", "")] + list(c.get("aliases", []))
        out[c["ticker"]] = sorted({n.lower() for n in names if n}, key=len, reverse=True)
    return out


def resolve_ticker(name: str) -> str | None:
    """A single name -> ticker, or None if it is not a corpus company."""
    key = re.sub(r"[^a-z0-9é ]", "", name.lower()).strip()
    if not key:
        return None
    for ticker, names in _aliases().items():
        if key in names:
            return ticker
    for ticker, names in _aliases().items():          # "HDFC Bank Ltd" -> hdfc bank
        if any(re.search(rf"\b{re.escape(a)}\b", key) for a in names):
            return ticker
    return None


def find_companies(text: str) -> list[str]:
    """Tickers of all corpus companies mentioned in `text`, in order of first appearance."""
    low = text.lower()
    hits = []
    for ticker, names in _aliases().items():
        pos = [m.start() for a in names for m in re.finditer(rf"\b{re.escape(a)}\b", low)]
        if pos:
            hits.append((min(pos), ticker))
    return [t for _, t in sorted(hits)]
