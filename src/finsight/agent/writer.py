# ORIGINAL PLACEHOLDER (kept):
# """Writer node (LLM->JSON, schemas.Answer): drafts the final answer with formula, inputs, and
# citations, using only tool outputs. Prompt in prompts/writer.md. TODO (Week 2)."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
"""Writer node. Builds the final answer object (schemas.AgentAnswer).

The value, unit, formula, inputs and citations are filled in by CODE from the executor's tool results.
The model is asked only for the wording of the sentence (prompts/writer.md). `template()` writes the same
sentence in code; it is what the model is given as "facts" and what is used if the model's wording is
rejected twice by the critic. So a model failure can cost style, never correctness.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from finsight.corpus import fy_label
from finsight.schemas import AgentAnswer, AgentPlan, Draft, SummaryDraft
from finsight.tools.get_company_profile import get_company_profile
from finsight.tools.glossary import derived_inputs, get_metric, reported_metrics

_UPPER = {"casa": "CASA", "npa": "NPA", "crar": "CRAR", "ebit": "EBIT", "ebitda": "EBITDA"}


@lru_cache(maxsize=1)
def _prompts() -> tuple[str, str]:
    text = (Path(__file__).parent / "prompts" / "writer.md").read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    numeric, summary = text.split("=====SUMMARY=====")
    return numeric.strip(), summary.strip()


def _name(ticker: str) -> str:
    return get_company_profile(ticker)["name"]


def _num(v: float, unit: str | None) -> str:
    if unit in ("percent", "%"):
        return f"{v:.2f}%"
    if unit in ("ratio", "times"):
        return f"{v:.2f} times"
    if unit in ("currency_per_share", "Rs"):
        return f"₹{v:,.2f}"
    return f"₹{v:,.2f} {unit or ''}".strip()


def _label(plan: AgentPlan) -> str:
    words = (plan.metric if plan.metric and plan.metric != "yoy_change" else plan.item or "figure").split("_")
    return " ".join(_UPPER.get(w, w) for w in words)


def template(plan: AgentPlan, result: dict) -> str:
    """A plain, always-correct sentence written by code."""
    fy, scope, label = fy_label(plan.fiscal_years[-1]), plan.scope, _label(plan)
    vals = result["values"]
    if plan.intent == "compare_rank":
        rk = result["ranking"]
        unit = next(iter(vals.values()))["unit"]
        parts = ", ".join(f"{_name(r['name'])} {_num(r['value'], unit)}" for r in rk["ranking"])
        lead = "It is a tie at the top" if rk["tie"] else f"{_name(rk['winner'])} had the {rk['order']} {label}"
        return f"{lead} in {fy} ({scope}). In order: {parts}."
    c, v = next(iter(vals.items()))
    # NEW (19 Nov 2026): a share worked out from the report text names the two rows it used (executor.text_ratio).
    # No scope in the sentence: the page that was read decides it, and base_answer() adds it as a note.
    if plan.metric == "share_from_report" and plan.intent != "compare_rank":
        labels = v.get("labels") or ["The share"]
        if len(labels) == 2:
            return f"For {_name(c)}, {labels[0]} was {v['value']:.2f}% of {labels[1]} in {fy}."
        return f"For {_name(c)}, the report states {labels[0]} as {v['value']:.2f}% in {fy}."
    if plan.metric == "yoy_change":
        direction = "rose" if v["value"] >= 0 else "fell"
        return (f"{_name(c)}'s {label} ({scope}) {direction} {abs(v['value']):.2f}% from {_num(v['previous'], 'crore')} in "
                f"{fy_label(plan.fiscal_years[0])} to {_num(v['current'], 'crore')} in {fy}, "
                f"a change of {_num(v['absolute_change'], 'crore')}.")
    return f"{_name(c)}'s {label} was {_num(v['value'], v['unit'])} in {fy} ({scope})."


# OLD: def formula_for(plan: AgentPlan) -> str | None:
# NEW (19 Nov 2026): takes the executor's result too, because a share worked out from the report text has its
# formula ("numerator / denominator * 100", or none when the report states the percentage) in the result.
def formula_for(plan: AgentPlan, result: dict | None = None) -> str | None:
    """The glossary formula behind a computed metric or a derived item (None for a plain lookup)."""
    if plan.metric == "share_from_report":
        vals = (result or {}).get("values") or {}
        return next(iter(vals.values())).get("formula") if vals else None
    if plan.metric and plan.metric not in reported_metrics():
        is_bank = bool(get_company_profile(plan.companies[0])["is_bank"])
        return get_metric(plan.metric, is_bank)["formula"]
    if plan.item in derived_inputs():
        return derived_inputs()[plan.item]["formula"]
    return None


def base_answer(plan: AgentPlan, result: dict) -> AgentAnswer:
    vals, figs = result["values"], result["figures"]
    a = AgentAnswer(status="answered", intent=plan.intent, companies=plan.companies, fiscal_years=plan.fiscal_years,
                    scope=plan.scope, metric=plan.metric or plan.item, inputs=figs, formula=formula_for(plan, result),   # 19 Nov 2026: + result
                    citations=sorted({f.citation for f in figs if f.citation}))
    if plan.intent == "compare_rank":
        a.ranking = [r["name"] for r in result["ranking"]["ranking"]]
        a.answer_company = result["ranking"]["winner"]
        a.unit = next(iter(vals.values()))["unit"]
    else:
        v = next(iter(vals.values()))
        a.value, a.unit = v["value"], v["unit"]
    # NEW (19 Nov 2026, later): say so when a figure for one year is read from another year's report.
    # WHY: see app/components.py (input_rows). "FY2024-25 ... page 354" was looked up in the wrong report.
    for f in figs:
        m = re.search(r"-FY(\d\d)(\d\d)-p", f.citation or "")
        report = f"20{m.group(1)}-{m.group(2)}" if m else None
        if report and report != f.fiscal_year:
            note = (f"The {fy_label(f.fiscal_year)} figure is read from the previous-year column of the {fy_label(report)} "
                    f"report (page {f.page}), so both years are on the same basis.")
            if note not in a.caveats:
                a.caveats.append(note)
    # NEW (19 Nov 2026): say plainly what was and was not checked for a share read from the report text.
    if plan.metric == "share_from_report":
        a.caveats.append("These numbers were picked from the report text and checked to be printed on the cited page. "
                         "Please confirm that they are the right rows and the right year's column.")
        scopes = {v.get("page_scope") for v in vals.values() if v.get("page_scope")}
        if len(scopes) == 1:
            a.caveats.append(f"The cited page belongs to the {scopes.pop()} statements.")
    if any(f.unit.lower() in ("thousand", "million", "lakh", "billion") for f in figs):
        a.caveats.append("Amounts are converted to ₹ crore from the unit used in the report.")
    return a


def write(plan: AgentPlan, result: dict, llm=None, use_model: bool = True) -> AgentAnswer:
    a = base_answer(plan, result)
    a.answer = template(plan, result)
    if llm and use_model:
        d = llm.json(_prompts()[0], f"Facts: {a.answer}", Draft, max_tokens=220)
        if d.answer.strip():
            a.answer = d.answer.strip()
    return a


def write_summary(plan: AgentPlan, result: dict, llm) -> AgentAnswer:
    passages = result["passages"]
    user = (f"Topic: {plan.topic}\nCompany: {_name(plan.companies[0])}, {fy_label(plan.fiscal_years[-1])}\n\n"
            + "\n\n".join(f"[{p['citation']}]\n{p['text']}" for p in passages))
    s = llm.json(_prompts()[1], user, SummaryDraft, max_tokens=600)
    points = [k.model_copy(update={"citation": k.citation.strip("[] ")}) for k in s.key_points]
    return AgentAnswer(status="answered", intent="summary", companies=plan.companies, fiscal_years=plan.fiscal_years,
                       answer=s.answer, key_points=points, citations=sorted({k.citation for k in points}))
