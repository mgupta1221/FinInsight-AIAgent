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
# CHANGED again (18 Nov 2026): "=", "_" and ":" are accepted between the two parts of a year.
# OLD (15 Nov): the separator class was [-–/] in all three places.
# WHY: "FY2024=25" (the "=" key is next to "-") was read as "FY2024" alone, i.e. FY2023-24, and refused as
#      "not in my corpus", although the intended year is obvious.
_SEP = r"[-–/=_:]"
_FY = re.compile(rf"\b(?:fy\s?)?(20\d\d)\s?{_SEP}\s?(?:20)?(\d\d)\b|\bfy\s?(20\d\d|\d\d)\b(?!\s?{_SEP}\s?\d)|"
                 rf"\b(?:fy\s?)?(\d\d)\s?{_SEP}\s?(\d\d)\b", re.I)


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


# NEW (19 Nov 2026): repair digits that one report prints with a private font.
# WHY: in the TCS FY2024-25 PDF the text layer stores many digits as letters of another alphabet: "134.19" is
#      stored as "13\u03f0.19", "152" as "1\u03f12". On screen it looks right; in the extracted text it does not.
#      So "Which had the higher basic EPS in FY2024-25, Infosys or TCS?" failed: the EPS the model pointed at
#      (134.19) was "not printed" on the page as far as the code could see. The ten code points U+03EC..U+03F5
#      stand for 0..9 in that font, and a few punctuation marks are mapped the same way.
_GLYPHS = {0x3EC + d: str(d) for d in range(10)}
_GLYPHS.update({0x439: "%", 0x358: ".", 0x357: ":", 0x380: "(", 0x381: ")", 0x36C: "/", 0xF24: "\u20b9"})


def fix_glyphs(text: str) -> str:
    """Text with the private-font digits of the TCS FY2024-25 report turned back into 0-9. Other text is unchanged."""
    return text.translate(_GLYPHS) if text else text
