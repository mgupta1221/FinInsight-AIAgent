"""Assign each page to a report section using the heading patterns in config/sections.yaml.

Simple, robust approach: walk pages in order; when a page's text contains a section heading pattern,
that section becomes "current"; every page inherits the current section. Pages before any heading are
tagged "front_matter" and skipped at chunking time. Only the sections listed in sections.yaml are
kept (financial statements, notes, MD&A, risk, highlights, + Basel III for banks).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from finsight.config import settings


@lru_cache(maxsize=1)
def _load_sections() -> list[dict]:
    with open(settings.config_dir / "sections.yaml", encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("ingest_sections", [])


def assign_sections(pages: list[dict], is_bank: bool = False) -> list[dict]:
    """Return pages with an added 'section' key (section 'key' from sections.yaml or 'front_matter')."""
    specs = [s for s in _load_sections() if not (s.get("banks_only") and not is_bank)]
    current = "front_matter"
    out = []
    for pg in pages:
        low = pg["text"].lower()
        for spec in specs:
            if any(pat in low for pat in spec["patterns"]):
                current = spec["key"]
                break
        out.append({**pg, "section": current})
    return out


def keep_keys() -> set[str]:
    return {s["key"] for s in _load_sections()}
