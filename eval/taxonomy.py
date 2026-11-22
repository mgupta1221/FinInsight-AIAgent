# ORIGINAL PLACEHOLDER (kept):
# """Label each wrong answer by failure type (retrieval_miss, wrong_item, wrong_period_or_statement,
# unit_error, calc_error, tool_call_error, hallucination, control). TODO (Week 2)."""
#
# IMPLEMENTED (21 Nov 2026).
"""Label each wrong answer with ONE failure type, by rule. The labels are the eight named in the project plan.

  control                    did the wrong thing: answered where it had to refuse or ask, or the reverse
  tool_call_error            the run failed or was stopped (step / token limit, endpoint, search down, planning)
  retrieval_miss             the figure or passage was not found; a summary that misses most key points
  unit_error                 right figure, wrong scale (crore against million and so on)
  wrong_period_or_statement  standalone against consolidated, or another year
  wrong_item                 a number from a page gold does not use (another line or table)
  calc_error                 the gold page was read, yet the result differs (formula, line or order)
  hallucination              free-text answer with a number that is not the gold value and has no gold page behind it

A rule can only guess the cause from what was saved. The label is a starting point for reading the trace, and the
`why` column says which rule fired.
"""
from __future__ import annotations

import collections
import re

from score import FREE_TEXT, SCALES, close, numbers_in   # noqa: E402  (same folder; eval/ is on sys.path when run as a script)

LABELS = ["control", "tool_call_error", "retrieval_miss", "unit_error", "wrong_period_or_statement", "wrong_item",
          "calc_error", "hallucination"]
_STOPPED = re.compile(r"limit|budget|could not plan|unavailable|try again|the run failed|stopped", re.I)
_MISSING = re.compile(r"no figure for|could not find|nothing found|not found", re.I)


def _scaled(got: float, gold: float) -> bool:
    # CHANGED (21 Nov 2026).  OLD: any(close(got * f, gold) or close(got / f, gold) for f in ...)
    # WHY: `close` also allows a small absolute difference, so 1.49 against 0.011 (multihop-006) counted as
    #      "the same value at another scale". A scale error is judged by ratio only.
    if not gold:
        return False
    return any(abs(got * f / gold - 1) <= 0.005 or abs(got / f / gold - 1) <= 0.005 for f in list(SCALES.values()) + [10.0])


def label(row: dict, q: dict, a: dict) -> tuple[str, str]:
    """(label, why) for one WRONG row of the score sheet."""
    gold, status, text = q.get("gold") or {}, a.get("status"), a.get("answer") or ""
    expect = gold.get("expect")
    wants_answer = expect in ("answer", "ignore_injection", "summary")
    if status == "error":
        return "tool_call_error", "the run raised an error"
    if not wants_answer:
        return "control", "gold expects a refusal, a clarifying question or 'does not apply'"
    if status in ("clarify", "refused") and a.get("mode") != "simple":
        return "control", f"asked back or refused (status {status}) where gold has an answer"
    if status == "escalated":
        if _MISSING.search(text):
            return "retrieval_miss", "the agent said it could not find the figure"
        if _STOPPED.search(text):
            return "tool_call_error", "the run was stopped before an answer"
        return "calc_error", "the answer could not be verified by the critic"
    if expect == "summary":
        return "retrieval_miss", "the summary covers too few of the gold key points"
    if "ranking" in gold:
        return "calc_error", "the order of the companies differs from gold"
    g = gold.get("value")
    # OLD: if a.get("mode") == "simple":
    # CHANGED (22 Nov 2026): the same rule for the baselines without the reports. There, "hallucination" is a wrong
    # figure given from memory and "retrieval_miss" is an answer with no figure ("I do not know").
    if a.get("mode") in FREE_TEXT:
        if row.get("page_match"):
            return "calc_error", "a gold page was retrieved, but the value in the text is not the gold value"
        return ("hallucination" if numbers_in(text) else "retrieval_miss"), "free-text answer without the gold value or a gold page"
    v = a.get("value")
    if v is not None and g is not None and _scaled(float(v), float(g)):
        return "unit_error", "the value equals gold at another scale"
    if row.get("scope_expected") and row.get("scope_got") and row["scope_expected"] != row["scope_got"]:
        return "wrong_period_or_statement", f"answered {row['scope_got']}, gold is {row['scope_expected']}"
    if q.get("fiscal_year") and a.get("fiscal_years") and q["fiscal_year"] not in a["fiscal_years"]:
        return "wrong_period_or_statement", f"answered for {a['fiscal_years']}, gold is {q['fiscal_year']}"
    if row.get("page_match") is False:
        return "wrong_item", "none of the cited pages is a gold page"
    return "calc_error", "a gold page was cited, but the value differs"


def label_all(scored: list[dict], questions: list[dict], answers: list[dict]) -> list[dict]:
    qs, ans = {q["id"]: q for q in questions}, {a["id"]: a for a in answers}
    out = []
    for row in scored:
        if not row["correct"]:
            name, why = label(row, qs[row["id"]], ans[row["id"]])
            out.append({"id": row["id"], "type": row["type"], "label": name, "why": why, "status": row["status"],
                        "expected": row["expected"], "got": row["got"], "question": row["question"], "answer": row["answer"]})
    return out


def counts(errors: list[dict]) -> dict[str, int]:
    c = collections.Counter(e["label"] for e in errors)
    return {name: c.get(name, 0) for name in LABELS if c.get(name)}
