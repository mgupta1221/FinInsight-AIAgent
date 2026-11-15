# ORIGINAL PLACEHOLDER (kept):
# """Critic node (code + 1 LLM call, schemas.CriticVerdict): rejects any answer whose numbers aren't
# traceable to a tool, whose pages aren't cited, whose formula != glossary, or that gives advice.
# Fail -> back to planner (max 2 retries) -> else escalate. Prompt in prompts/critic.md. TODO (Week 2)."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026), in code only (no model call). The reasons are in prompts/critic.md.
"""Critic node (code). Decides whether a drafted answer may be shown as verified.

Checks: every number in the wording is traceable to a tool result; every figure has a page citation; the
formula is the glossary formula; the fiscal year and scope match the plan; nothing reads as advice or a
forecast; a summary cites only retrieved pages.
"""
from __future__ import annotations

import re

from finsight.corpus import fy_label
from finsight.schemas import AgentAnswer, AgentPlan, Verdict

ADVICE = re.compile(r"\b(buy|sell|hold|invest(ors? should)?|undervalued|overvalued|recommend|attractive|bullish|bearish|"
                    r"will (grow|rise|fall|increase|decrease)|is expected to|outlook is)\b", re.I)
NUMBER = re.compile(r"(?<![\w-])\(?-?\d[\d,]*(?:\.\d+)?\)?%?")


def _numbers(text: str) -> list[float]:
    """Numbers in the wording, ignoring fiscal years and dates."""
    text = re.sub(r"FY\s?20\d\d[-–]\d\d|\b20\d\d[-–]\d\d\b|\b(19|20)\d\d\b|\b31 March\b|\bMarch 31\b", " ", text)
    out = []
    for m in NUMBER.finditer(text):
        try:
            out.append(abs(float(m.group().strip("()%").replace(",", ""))))
        except ValueError:
            pass
    return out


def _allowed(result: dict) -> list[float]:
    ok: list[float] = [abs(f.value) for f in result.get("figures", [])]
    for v in result.get("values", {}).values():
        for k in ("value", "current", "previous", "absolute_change"):
            if v.get(k) is not None:
                ok.append(abs(float(v[k])))
        ok += [abs(float(x)) for x in (v.get("inputs") or {}).values()]
    for r in (result.get("ranking") or {}).get("ranking", []):
        ok.append(abs(float(r["value"])))
    return ok


def _traceable(n: float, allowed: list[float]) -> bool:
    return any(abs(n - a) <= max(0.006, 0.0006 * abs(a)) for a in allowed)


def review(answer: AgentAnswer, plan: AgentPlan, result: dict, expected_formula: str | None = None) -> Verdict:
    reasons: list[str] = []
    if plan.intent == "summary":
        retrieved = {p["citation"] for p in result.get("passages", [])}
        if len(answer.key_points) < 3:
            reasons.append("fewer than 3 key points")
        bad = [k.citation for k in answer.key_points if k.citation not in retrieved]
        if bad:
            reasons.append(f"key points cite pages that were not retrieved: {sorted(set(bad))}")
        text = answer.answer + " " + " ".join(k.point for k in answer.key_points)
    else:
        if not answer.inputs:
            reasons.append("no input figures")
        if any(not f.citation or not f.page for f in answer.inputs):
            reasons.append("an input figure has no page citation")
        if not {f.citation for f in answer.inputs} <= set(answer.citations):
            reasons.append("citations do not cover every input")
        if expected_formula is not None and answer.formula != expected_formula:
            reasons.append("formula is not the glossary formula")
        loose = [n for n in _numbers(answer.answer) if not _traceable(n, _allowed(result))]
        if loose:
            reasons.append(f"numbers not traceable to a tool result: {loose[:4]}")
        year = plan.fiscal_years[-1]
        if year not in answer.answer and fy_label(year) not in answer.answer:
            reasons.append(f"answer does not state the fiscal year {fy_label(year)}")
        other = "standalone" if plan.scope == "consolidated" else "consolidated"
        if other in answer.answer.lower() and str(plan.scope) not in answer.answer.lower():
            reasons.append("answer states the wrong scope")
        text = answer.answer
    if ADVICE.search(text):
        reasons.append("wording reads as advice or a forecast")
    return Verdict(ok=not reasons, reasons=reasons)
