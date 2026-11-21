"""Assign each page to a report section using the heading patterns in config/sections.yaml.

Simple, robust approach: walk pages in order; when a page's text contains a section heading pattern,
that section becomes "current"; every page inherits the current section. Pages before any heading are
tagged "front_matter" and skipped at chunking time. Only the sections listed in sections.yaml are
kept (financial statements, notes, MD&A, risk, highlights, + Basel III for banks).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from finsight.config import settings


@lru_cache(maxsize=1)
def _load_sections() -> list[dict]:
    with open(settings.config_dir / "sections.yaml", encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("ingest_sections", [])


# CHANGED (18 Nov 2026): assign_sections was rewritten. The previous version is kept as comments at the
# bottom of this file; config/sections.yaml explains what was wrong and lists the rules.
_STATEMENTS = ("pnl", "balance_sheet", "cash_flow")
_FINANCIAL = {"notes", "auditor", *_STATEMENTS}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u2019", "'").replace("\u2018", "'").lower()).strip()


def headings_in(text: str, specs: list[dict]) -> list[str]:
    """Section keys whose pattern is a HEADING in `text`: a line of 4-130 characters that starts with the
    pattern, or of which the pattern is at least 35%. One key per line, in line order."""
    mdna = next((s["patterns"] for s in specs if s["key"] == "mdna"), [])
    out = []
    for raw in text.split("\n"):
        line = _norm(raw)
        if not (4 <= len(line) <= 130):
            continue
        start = re.sub(r"^[^a-z]+", "", line)
        for spec in specs:
            if any(start.startswith(p) or (p in line and len(p) / len(line) >= 0.35) for p in spec["patterns"]):
                key = spec["key"]
                if key == "directors_report" and any(m in line for m in mdna):
                    key = "mdna"                    # "Report of the Board of Directors and Management Discussion & Analysis"
                out.append(key)
                break
    return out


def assign_sections(pages: list[dict], is_bank: bool = False, statement_pages: dict | None = None) -> list[dict]:
    """Return pages with added 'section' and 'scope' keys.

    statement_pages: {page: (statement, scope)} from ingest.statements.extract_statement_rows. Those pages get
    the statement as their section and its scope; the notes that follow inherit that scope. Without it, the
    statement patterns in sections.yaml are used as headings (less exact).
    """
    specs = [s for s in _load_sections() if not (s.get("banks_only") and not is_bank)]
    by_key = {s["key"]: s for s in specs}
    narrative = [s for s in specs if statement_pages is None or s["key"] not in _STATEMENTS]
    default = next((s["key"] for s in specs if s.get("default")), "front_matter")
    current, previous, age, scope = default, default, 0, ""
    out = []
    for pg in pages:
        number = pg.get("page")
        if statement_pages and number in statement_pages:
            statement, scope = statement_pages[number]
            out.append({**pg, "section": statement, "scope": scope})
            current, age = "notes", 0                       # what follows a statement is its notes
            continue
        lines = [l for l in pg["text"].split("\n") if l.strip()]
        on_page = headings_in(pg["text"], narrative)
        top = headings_in("\n".join(lines[:12]), narrative)
        label = current
        in_financials = current in _FINANCIAL
        if len(set(on_page)) >= 3 and not in_financials:
            pass                                            # a table of contents names many sections: no change
        elif top and not (in_financials and by_key[top[0]].get("not_in_financials")):
            head = top[0]
            if by_key[head].get("one_page"):
                label = head
            else:
                if head != current:
                    previous = current if current not in _FINANCIAL else previous
                current, label, age = head, head, 0
        age += 1
        limit = by_key.get(current, {}).get("max_pages")
        if limit and age > limit and label == current:      # a short section ran on without a heading: it has ended
            current = label = previous
            age = 0
        if label not in _FINANCIAL:
            scope = ""                                      # scope applies to statements and their notes only
        out.append({**pg, "section": label, "scope": scope})
    return out


def keep_keys() -> set[str]:
    return {s["key"] for s in _load_sections()}


# ---------------- PREVIOUS VERSION (kept for reference, replaced 18 Nov 2026) ----------------
# def assign_sections(pages: list[dict], is_bank: bool = False) -> list[dict]:
#     """Return pages with an added 'section' key (section 'key' from sections.yaml or 'front_matter')."""
#     specs = [s for s in _load_sections() if not (s.get("banks_only") and not is_bank)]
#     current = "front_matter"
#     out = []
#     for pg in pages:
#         low = pg["text"].lower()
#         for spec in specs:
#             if any(pat in low for pat in spec["patterns"]):
#                 current = spec["key"]
#                 break
#         out.append({**pg, "section": current})
#     return out
