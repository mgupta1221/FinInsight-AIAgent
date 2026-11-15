"""Small helpers about the corpus that several agent modules share.

NEW FILE (agent layer, 13 Nov 2026).

WHY: the fiscal years, the "previous year" rule, the citation format and the way a year written by a user
("FY26", "2025-26", "FY2025-26") is normalised were needed by the guard, the planner, the executor and the
tools. Keeping them in one place means there is one definition of each, taken from config/companies.yaml.

Inside this project a fiscal year is always the string "2025-26" (no "FY" prefix), exactly as in
config/companies.yaml and eval/eval_set.jsonl. `fy_label()` adds the "FY" only for display.
"""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from finsight.config import settings


@lru_cache(maxsize=1)
def fiscal_years() -> list[str]:
    """Years in the corpus, oldest first, e.g. ["2024-25", "2025-26"] (from companies.yaml defaults)."""
    with open(settings.config_dir / "companies.yaml", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return sorted(data.get("defaults", {}).get("fiscal_years", ["2024-25", "2025-26"]))


def previous_year(fy: str) -> str:
    """"2025-26" -> "2024-25"."""
    start = int(fy[:4]) - 1
    return f"{start}-{(start + 1) % 100:02d}"


def known_years() -> set[str]:
    """Years a question may mention: the corpus years plus the prior-year column of the oldest report."""
    ys = fiscal_years()
    return set(ys) | {previous_year(ys[0])}


def fy_label(fy: str) -> str:
    return fy if fy.upper().startswith("FY") else f"FY{fy}"


def normalise_fy(text: str) -> str | None:
    """'FY2025-26', '2025-26', 'FY26', 'fy 2026' -> '2025-26'. None if it cannot be read."""
    t = text.lower().replace(" ", "").replace("–", "-")
    m = re.search(r"(20\d\d)-(\d\d)", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.search(r"fy(?:20)?(\d\d)$", t)
    if m:
        end = int(m.group(1))
        return f"20{end - 1:02d}-{end:02d}"
    return None


# OLD (kept):
# _FY = re.compile(r"\b(?:fy\s?)?(20\d\d\s?[-–]\s?\d\d)\b|\bfy\s?(20\d\d|\d\d)\b", re.I)
#
# def years_in(text: str) -> list[str]:
#     out: list[str] = []
#     for m in _FY.finditer(text):
#         fy = normalise_fy(m.group(1) or ("fy" + m.group(2)))
#         if fy and fy not in out:
#             out.append(fy)
#     return out
#
# CHANGED (15 Nov 2026): the short forms "24-25", "FY24-25", "2024-2025" and "2024/25" are read as well.
# WHY: the follow-up "and for 25-26" was not recognised as a year at all. The agent then silently reused the
#      year in memory, which is a wrong answer whenever the remembered year differs from the one typed.
#      A two-digit pair counts only when the second number follows the first ("24-25"), so page ranges such
#      as "24-30" are not taken for a year.
_FY = re.compile(r"\b(?:fy\s?)?(20\d\d)\s?[-–/]\s?(?:20)?(\d\d)\b|\bfy\s?(20\d\d|\d\d)\b(?!\s?[-–/]\s?\d)|"
                 r"\b(?:fy\s?)?(\d\d)\s?[-–/]\s?(\d\d)\b", re.I)


def years_in(text: str) -> list[str]:
    """All fiscal years mentioned in a piece of text, in order, normalised."""
    out: list[str] = []
    for m in _FY.finditer(text):
        long_start, long_end, single, short_start, short_end = m.groups()
        if long_start:
            fy = f"{long_start}-{long_end}" if int(long_end) == (int(long_start) + 1) % 100 else None
        elif single:
            fy = normalise_fy("fy" + single)
        else:
            fy = f"20{short_start}-{short_end}" if int(short_end) == (int(short_start) + 1) % 100 else None
        if fy and fy not in out:
            out.append(fy)
    return out


def citation(ticker: str, report_fy: str, page: int) -> str:
    """INFY, "2025-26", 214 -> "INFY-FY2526-p214" (the SPEC section 7 format; same as the existing tools)."""
    yy = report_fy.replace("FY", "").replace("-", "")[2:]
    return f"{ticker}-FY{yy}-p{page}"
