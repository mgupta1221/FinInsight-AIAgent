# ORIGINAL PLACEHOLDER (kept):
# """Patterns + checks for prompt injection, investment-advice/forecast requests, and
# out-of-corpus detection. Used by agent/guard.py. TODO (Week 2/3)."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026). This file was a one-line TODO; it now holds the refusal rules.
# WHY rules in code and not in a prompt: a refusal must be certain and must cost no tokens. A pattern match
# before any model call guarantees both ("Should I buy TCS shares?" is refused with zero API usage).
"""Refusal rules for the guard: prompt injection, advice, forecasts, insider, tax/legal, years outside the corpus."""
from __future__ import annotations

import re

from finsight.corpus import fiscal_years, fy_label, known_years, years_in

RULES: list[tuple[str, re.Pattern]] = [
    ("injection", re.compile(r"ignore (all |any |the )?(previous|prior|above|your|earlier) (instructions|rules|prompt)|"
                             r"disregard (all |any |the |your )?(previous |prior )?(instructions|rules)|system prompt|"
                             r"reveal (your|the) (prompt|instructions)|you are now|pretend (to be|you are)|jailbreak", re.I)),
    # CHANGED (15 Nov 2026): the last pattern line was added. The first four lines are the old rule, unchanged.
    # WHY: "What is best price to buy TCS?" was NOT refused. The old patterns needed wording such as
    #      "should I buy" or "price target"; a plain "to buy" slipped through, and the agent then answered with
    #      the net profit left in memory from the previous question. Any question that uses buy / sell /
    #      invest in as a verb, or asks for a best / right price or time, is an advice request.
    #      ("buyback", "selling expenses", "investing activities" and "shareholders" do not match: \b needs
    #      the whole word.)
    ("advice", re.compile(r"\b(should|shall|can|could) (i|we|one) (buy|sell|hold|invest)|\b(buy|sell|hold) (or|and) (sell|hold|buy)\b|"
                          r"good (investment|buy|stock)|worth (buying|investing)|price target|target price|fair (price|value)|"
                          r"\brecommend\w* .*(stock|share|invest)|is it (a good )?time to (buy|sell|invest)|"
                          r"(under|over)valued|"
                          r"\b(buy|sell)\b(?!-)|\binvest(ing)? in\b|\b(best|right|good|ideal) (price|time|level|moment)\b|"
                          r"\b(entry|exit) (price|point|level)\b|stock tips?\b|multibagger", re.I)),
    ("forecast", re.compile(r"\b(predict|forecast|project(ion)?|estimate)\w*\b.*\b(revenue|profit|earnings|results|margin|growth|price)|"
                            r"\bwill\b.*\b(revenue|profit|earnings|share price|stock)\b.*\b(be|grow|rise|fall|increase|decrease)|"
                            r"next (year|quarter)'?s? (revenue|profit|earnings|results)", re.I)),
    ("non_public", re.compile(r"insider|non-?public|unannounced|confidential|leak(ed)?\b|upcoming results", re.I)),
    ("tax_legal", re.compile(r"tax (implication|liabilit|treatment|advice)|capital gains|legal advice|"
                             r"how (should|do|can) i (report|file|declare)|can i sue", re.I)),
]


def _years_text() -> str:
    return " and ".join(fy_label(y) for y in fiscal_years())


def message(reason: str) -> str:
    return {
        "advice": "I can't give investment advice. I can tell you what the annual reports say about revenue, margins or risks.",
        "forecast": f"I can't forecast future results. I can show the {_years_text()} figures the company reported.",
        "non_public": "I only use the published annual reports, so I can't help with non-public information.",
        "tax_legal": "I can't give tax or legal advice. I can answer questions about the published annual reports.",
        "injection": "I can't follow instructions that change my rules. Ask me about the annual reports in my corpus.",
        "not_in_corpus": f"That is not in my corpus. I cover 15 companies for {_years_text()}.",
    }[reason]


def check(question: str) -> tuple[str, str] | None:
    """Return (refusal_reason, message) if the question must be refused, else None."""
    for reason, rx in RULES:
        if rx.search(question):
            return reason, message(reason)
    bad = [y for y in years_in(question) if y not in known_years()]
    if bad:
        return "not_in_corpus", f"{fy_label(bad[0])} is not in my corpus. I cover {_years_text()}."
    return None
