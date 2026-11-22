"""Follow-up suggestions under an answer: two to four questions the user can ask next with one click.

NEW FILE (22 Nov 2026).

WHY: after "Infosys's net profit was ... in FY2025-26" a user often wants the other year, the change between
     the years, or a related figure, and has to know how to word it. The app now offers these as buttons.

How they are made: by code, from the answer just given (company, year, scope, figure). The model is not asked.
So only questions the agent can answer are offered: the other fiscal year in the corpus, the change between the
two years (for an amount, not for a ratio), and related figures from the same lists as the Quick lookup
(app/lookups.py), which already differ for banks and other companies. A suggestion is a complete question in
plain English and goes through the same agent as a typed one: same guard, same formulas, same check.

No Streamlit import here, so the rules can be unit-tested without a browser (tests/test_app.py).
"""
from __future__ import annotations

import lookups
from finsight.corpus import fiscal_years
from finsight.tools.get_company_profile import get_company_profile

RELATED = {False: ["Revenue from operations", "Net profit", "Operating margin", "Earnings per share"],
           True: ["Net profit", "Deposits", "CASA ratio", "Net interest margin"]}
TOPICS = [("business performance", "performance"), ("key risks", "risk"), ("strategy and outlook", "strateg"),
          ("management commentary", "commentary")]


def _figure(a, is_bank: bool):
    """(label, id, kind) of the figure or ratio an answer is about, or None if it is not one of the lookup lists."""
    options = {ident: (label, ident, kind) for label, ident, kind in lookups.figure_options(is_bank)}
    if a.metric in options:
        return options[a.metric]
    for f in a.inputs or []:                     # a plain figure: its name is the id (net_profit, deposits ...)
        if f.name in options:
            return options[f.name]
    return None


def suggestions(a, question: str = "") -> list[tuple[str, str]]:
    """[(text on the button, the full question it asks)] for one answer; [] if nothing sensible can be offered."""
    if getattr(a, "status", None) != "answered" or len(a.companies or []) != 1 or not a.fiscal_years:
        return []
    try:
        prof = get_company_profile(a.companies[0])
    except Exception:  # noqa: BLE001
        return []
    name, is_bank = prof["name"], bool(prof.get("is_bank"))
    years = fiscal_years()
    year = a.fiscal_years[-1]
    others = [y for y in years if y != year]
    out: list[tuple[str, str]] = []

    if a.intent == "summary":
        for topic, word in TOPICS:
            if word not in question.lower() and len(out) < 3:
                out.append((topic.capitalize(), f"Summarise the {topic} of {name} in FY{year}."))
        return out

    fig = _figure(a, is_bank)
    if a.intent not in ("fact", "ratio", "yoy") or fig is None:
        return []
    label, ident, kind = fig

    def scope_for(i: str) -> str:
        return "" if lookups.scope_is_fixed(i, is_bank) else (a.scope or "").capitalize()

    if a.intent != "yoy":
        for other in others[-1:]:
            out.append((f"Same for FY{other}", lookups.build_question([name], label, [other], scope_for(ident))))
        if kind == "figure" and len(years) >= 2:
            out.append((f"Change from FY{years[0]} to FY{years[-1]}", lookups.build_question([name], label, [years[0], years[-1]], scope_for(ident))))
    known = {lab: (lab, i, k) for lab, i, k in lookups.figure_options(is_bank)}
    for lab in RELATED[is_bank]:
        if lab != label and lab in known and len(out) < 4:
            _, i, k = known[lab]
            if a.intent == "yoy":
                if k == "figure":
                    out.append((f"{lab}: change", lookups.build_question([name], lab, [years[0], years[-1]], scope_for(i))))
            else:
                out.append((lab, lookups.build_question([name], lab, [year], scope_for(i))))
    return out[:4]
