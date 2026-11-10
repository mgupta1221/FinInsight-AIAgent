"""Tool: get_company_profile.

Looks up a company in config/companies.yaml by name or ticker (case-insensitive, tolerant of
common variants) and returns its profile: sector, is_bank / is_nbfc, fiscal-year end, reporting
units, pdf prefix, and the fiscal years in the corpus. Raises ToolError for anything not in the
corpus (so the guard/planner can refuse out-of-corpus questions).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from finsight.config import settings
from finsight.tools.base import ToolError, register


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


@lru_cache(maxsize=1)
def _load(path: str | None = None) -> tuple[dict, dict]:
    cpath = Path(path) if path else settings.config_dir / "companies.yaml"
    if not cpath.exists():
        raise ToolError(f"companies file not found: {cpath}")
    with open(cpath, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    defaults = data.get("defaults", {})
    index: dict[str, dict] = {}
    for c in data.get("companies", []):
        profile = {**defaults, **c}
        for key in (c.get("name", ""), c.get("ticker", ""), c.get("pdf_prefix", "")):
            if key:
                index[_norm(key)] = profile
    return index, defaults


@register("get_company_profile")
def get_company_profile(company: str) -> dict:
    """Return the profile dict for a company name/ticker. Raises ToolError if not in corpus."""
    index, _ = _load()
    key = _norm(company)
    if key in index:
        return dict(index[key])
    # partial match fallback (e.g. "HDFC Bank" vs "HDFC")
    hits = [p for k, p in index.items() if key and (key in k or k in key)]
    if len(set(p["ticker"] for p in hits)) == 1:
        return dict(hits[0])
    raise ToolError(f"company '{company}' is not in the corpus")


def in_corpus(company: str) -> bool:
    try:
        get_company_profile(company)
        return True
    except ToolError:
        return False
