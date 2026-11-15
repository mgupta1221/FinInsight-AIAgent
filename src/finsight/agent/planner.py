# ORIGINAL PLACEHOLDER (kept):
# """Planner node (LLM->JSON, schemas.Plan): breaks the question into steps and fills slots;
# emits a clarify_question when a slot is missing/ambiguous. Few-shot plans in prompts/planner.md.
# TODO (Week 2)."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
"""Planner node. Three parts:

  draft_plan   (model) reads the question and fills the slots (schemas.AgentPlan), using prompts/planner.md.
  resolve      (code)  validates every slot, completes what the model missed, and raises Clarify or Refuse.
  build_steps  (code)  turns the validated plan into steps for the executor.

WHY the split: this is the main compensation for a small model. The model decides WHAT is being asked;
code guarantees the rest. If the model returns no company, a wrong statement line or the wrong intent, the
keyword rules below still find them in the question text, so a slip by the model does not become a wrong answer.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from finsight.corpus import fiscal_years, fy_label, previous_year, years_in
from finsight.schemas import AgentPlan, AgentStep
from finsight.tools.company_match import find_companies, resolve_ticker
from finsight.tools.get_company_profile import get_company_profile
from finsight.tools.glossary import _load as _glossary, derived_inputs, line_items, not_for_banks, reported_metrics

DEFAULT_SCOPE = "consolidated"

# If the model misses the metric, these phrases in the question settle it.
METRIC_WORDS = [("operating_margin", r"operating margin|ebit margin"), ("ebitda_margin", r"ebitda margin"),
                ("net_profit_margin", r"net profit margin|net margin|pat margin"),
                ("return_on_capital_employed", r"return on capital employed|\broce\b"),
                ("return_on_equity", r"return on equity|\broe\b"), ("return_on_assets", r"return on assets|\broa\b"),
                ("debt_to_equity", r"debt[- ]to[- ]equity|d/e ratio"), ("current_ratio", r"current ratio"),
                ("cost_to_income", r"cost[- ]to[- ]income"), ("gross_npa_ratio", r"gross npa|gnpa"),
                ("net_npa_ratio", r"net npa|nnpa"), ("casa_ratio", r"\bcasa\b"),
                ("net_interest_margin", r"net interest margin|\bnim\b"), ("crar", r"capital adequacy|\bcrar\b"),
                ("earnings_per_share", r"earnings per share|\beps\b")]
# Exact phrases: if one is in the question it wins, even over the model's choice of item.
ITEM_PHRASES = [("total_expenses", r"total expenses|total expenditure|total cost"), ("total_income", r"total income"),
                ("employee_benefits_expense", r"employee (benefits? )?(expenses?|costs?)|staff costs?|salary costs?"),
                ("depreciation", r"depreciation"), ("cash_and_cash_equivalents", r"cash and cash equivalents|cash balance"),
                ("net_interest_income", r"net interest income|\bnii\b"), ("ebitda", r"\bebitda\b"), ("ebit", r"\bebit\b"),
                ("profit_before_tax", r"profit before tax|\bpbt\b"), ("total_assets", r"total assets"),
                ("total_equity", r"total equity|net worth"), ("total_debt", r"total (debt|borrowings)"),
                ("finance_costs", r"finance costs?|interest costs?"), ("other_income", r"other income"),
                ("tax_expense", r"tax expense"), ("interest_earned", r"interest earned|interest income"),
                ("interest_expended", r"interest expended|interest expense"), ("operating_expenses", r"operating expenses"),
                ("revenue_from_operations", r"revenue from operations?"),
                ("net_profit", r"net profit|profit after tax|\bpat\b|profit for the year")]
# Loose words: used only when neither a phrase nor the model settles the item.
ITEM_WORDS = [("revenue_from_operations", r"revenue|sales|turnover"), ("net_profit", r"\bprofit\b|earnings"),
              ("deposits", r"deposits"), ("advances", r"\badvances\b|\bloans\b"), ("total_expenses", r"expenses")]
FOLLOW_UP = re.compile(r"^\s*(and|what about|how about|now|same|also|then)\b|\b(that|this|it|them|those)\b", re.I)


# NEW (15 Nov 2026): words that carry no topic of their own. Used by _unknown_words below.
_FILLER = set("""a an the of for in on at to by from with and or but if so than then now also too again just only
    what which who how when where why is are was were be been do does did has have had can could would will shall
    i we you me us my our your it its their them they that this these those there here one ones
    about same instead please show give tell find get see check look know want need like say said
    company companies bank banks firm year years fy fiscal financial annual report reports reported figure figures
    number numbers value values amount amounts much many standalone consolidated compare compared comparison versus vs
    between higher lower highest lowest more less most least than change changed changes grow grew growth increase
    increased decrease decreased rise rose fall fell up down over last previous prior current latest
    total net gross ratio ratios margin margins per cent percent percentage rs inr crore crores million lakh thousand
    summary summarise summarize summarised summarized describe key top main principal risk risks commentary
    management discussion strategy strategic priorities outlook ok okay thanks thank yes no not any all both each s""".split())


def _vocabulary() -> set[str]:
    """Every word the agent can map to a figure or ratio: glossary ids, labels and search keywords."""
    from finsight.tools.glossary import derived_inputs, line_items, reported_metrics
    words: set[str] = set()
    texts = list(all_metrics()) + list(all_items()) + list(derived_inputs())
    for spec in line_items().values():
        texts += list(spec.get("labels", []))
    for spec in reported_metrics().values():
        texts += [spec.get("search", "")] + list(spec.get("keywords", []))
    for _, rx in METRIC_WORDS + ITEM_PHRASES + ITEM_WORDS:
        texts.append(re.sub(r"[^a-z ]", " ", rx))                    # the words inside the patterns
    for t in texts:
        words |= set(re.findall(r"[a-z]+", t.lower().replace("_", " ")))
    return words


def _unknown_words(question: str, tickers: list[str]) -> list[str]:
    """Content words of the question that are not filler, not a company name and not finance vocabulary.

    NEW (15 Nov 2026). "And for Infosys?" -> []; "What is best price to buy TCS?" -> ['best', 'price', 'buy'].
    """
    from finsight.tools.company_match import _aliases
    names: set[str] = set()
    for t in tickers:
        for n in _aliases().get(t, []):
            names |= set(re.findall(r"[a-z]+", n.lower()))
    vocab = _vocabulary()
    return [w for w in re.findall(r"[a-z]+", question.lower()) if len(w) > 1 and w not in _FILLER and w not in names and w not in vocab]


# The words that make a question year-on-year (15 Nov 2026: moved here so two places use the same test).
YOY_WORDS = re.compile(r"\b(change[ds]?|grow(th|n)?|grew|increase[ds]?|decrease[ds]?|year[- ]on[- ]year|yoy|"
                       r"(compared? (with|to)|versus|vs\.?|over) (the )?(last|previous|prior) year)\b")


class Clarify(Exception):
    """The question cannot be answered until the user says more."""


class Refuse(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def all_metrics() -> list[str]:
    g = _glossary()
    return sorted(set(g["non_bank"]) | set(g["bank"]) | set(reported_metrics()))


def all_items() -> list[str]:
    return sorted(set(line_items()) | set(derived_inputs()))


def metric_kind(metric: str) -> str:
    """'reported' (looked up in the report text) or 'computed' (calculated from statement lines)."""
    return "reported" if metric in reported_metrics() else "computed"


def bank_only_metrics() -> set[str]:
    g = _glossary()
    return (set(g["bank"]) - set(g["non_bank"])) - {"earnings_per_share"}


@lru_cache(maxsize=1)
def system_prompt() -> str:
    text = (Path(__file__).parent / "prompts" / "planner.md").read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    return text.replace("<<METRICS>>", ", ".join(all_metrics())).replace("<<ITEMS>>", ", ".join(all_items()))


def draft_plan(question: str, memory: dict, llm) -> AgentPlan:
    context = f"\nPrevious question's slots: {memory}" if memory else ""
    return llm.json(system_prompt(), f"Q: {question}{context}", AgentPlan, max_tokens=300)


def _item_applies(item: str) -> str | None:
    return (line_items().get(item) or {}).get("applies")


def resolve(plan: AgentPlan, question: str, memory: dict) -> AgentPlan:
    """Validate and complete the slots in code. Raises Clarify or Refuse; returns a plan ready to execute."""
    q = question.lower()
    years_corpus = fiscal_years()
    # OLD: follow = bool(memory) and (plan.is_follow_up or bool(FOLLOW_UP.search(question)))
    # NEW (15 Nov 2026): a bare fragment such as "24-25?" or "standalone?" (only a year, a scope or a company
    # name, nothing else) is also a follow-up, whether or not the model says so.
    words = re.findall(r"[a-z]+", q)
    fragment = len(words) <= 4 and not _unknown_words(question, find_companies(question)) \
        and not any(w in _vocabulary() and w not in _FILLER for w in words)
    follow = bool(memory) and (plan.is_follow_up or bool(FOLLOW_UP.search(question)) or fragment)

    # companies: what the code finds in the question, plus resolvable names from the model
    tickers = find_companies(question)
    for name in plan.companies:
        t = resolve_ticker(name)
        if t and t not in tickers and name.lower() in q:
            tickers.append(t)
        elif not t and len(name) > 2 and name.lower() in q:
            raise Refuse("not_in_corpus", f"{name} is not in my corpus. I cover 15 companies for "
                         + " and ".join(fy_label(y) for y in years_corpus) + ".")
    if not tickers and follow:
        tickers = list(memory.get("companies", []))
    elif follow and plan.intent == "compare_rank" and len(tickers) == 1:
        tickers = list(dict.fromkeys(memory.get("companies", []) + tickers))       # "compare that with HDFC Bank"

    # NEW (15 Nov 2026): a "follow-up" that brings words the agent cannot place is really a NEW question.
    # WHY: after "net profit of TCS", the question "What is best price to buy TCS?" was answered with the net
    #      profit again. The model had marked it as a follow-up and copied the old item, so the code reused
    #      the remembered figure for a question that never asked for it. Now the remembered metric / item and
    #      the model's own metric / item are used for a follow-up only when every content word of the
    #      question is understood (filler, a company name, or finance vocabulary). Otherwise the agent asks
    #      which figure is wanted. Summary questions are free text by nature and are not checked.
    is_summary = bool(re.search(r"\b(summari[sz]e|summary|key risks|top risks|principal risks|commentary|describe|strategic priorities)\b", q))
    off_topic = follow and not is_summary and bool(_unknown_words(question, tickers))
    # NEW (15 Nov 2026): a follow-up that names NO figure at all ("and 24-25", "and for Infosys") keeps the
    # remembered metric / item; whatever metric or item the model sends for it is ignored.
    # WHY: with nothing to go on, the 8B model guesses (it sent "yoy_change" for "and 24-25"). Memory is exact.
    names_a_figure = any(w in _vocabulary() and w not in _FILLER for w in re.findall(r"[a-z]+", q))
    silent_follow_up = follow and not is_summary and not names_a_figure

    # metric and item: exact phrases first, then the model's choice, then loose words, then memory
    # OLD: metric = plan.metric if plan.metric in all_metrics() else None
    metric = plan.metric if plan.metric in all_metrics() and not off_topic and not silent_follow_up else None
    # NEW (15 Nov 2026): the model's metric "yoy_change" is accepted only if the question itself is year-on-year.
    # WHY: for the follow-up "and 24-25" the model returned intent "yoy" AND metric "yoy_change". The intent is
    #      corrected further down, but the metric stayed, which blocked the remembered metric (operating margin)
    #      and ended in "'None' is not a statement line". With the bogus metric removed, memory fills it in.
    says_yoy = len(years_in(question)) >= 2 or bool(YOY_WORDS.search(q))
    if metric == "yoy_change" and not says_yoy:
        metric = None
    if not metric:
        metric = next((m for m, rx in METRIC_WORDS if re.search(rx, q)), None)
    # OLD: item = next(... ITEM_PHRASES ...) or (plan.item if plan.item in all_items() else None)
    item = next((i for i, rx in ITEM_PHRASES if re.search(rx, q)), None) or (plan.item if plan.item in all_items() and not off_topic and not silent_follow_up else None)
    if not item and not (metric and metric != "yoy_change"):
        item = next((i for i, rx in ITEM_WORDS if re.search(rx, q)), None)
    # NEW (15 Nov 2026): in a follow-up, a word in the question beats an item the model merely copied from memory.
    # WHY: the model sees the remembered slots and tends to repeat them. "and its revenue?" after a net-profit
    #      question must switch to revenue, not answer net profit again.
    if follow and item and item == memory.get("item") and item == plan.item:
        spoken = next((i for i, rx in ITEM_WORDS if re.search(rx, q)), None)
        if spoken and spoken != item:
            item = spoken
    if metric and metric != "yoy_change":
        item = None
    # OLD: if not metric and not item and follow:
    if not metric and not item and follow and not off_topic:
        metric, item = memory.get("metric"), memory.get("item")

    # intent: decided in code where the wording is unambiguous
    intent = plan.intent
    if re.search(r"\b(summari[sz]e|summary|key risks|top risks|principal risks|commentary|describe|strategic priorities)\b", q):
        intent = "summary"
    # CHANGED (15 Nov 2026): two more wordings count as year-on-year, and the model can no longer choose "yoy" alone.
    # OLD:
    # elif len(years_in(question)) >= 2 or re.search(r"\b(change[ds]?|grow(th|n)?|grew|increase[ds]?|decrease[ds]?|year[- ]on[- ]year|yoy)\b", q):
    #     intent = "yoy"
    # elif intent == "other":
    #     intent = "ratio" if metric else "fact"
    # WHY: after "Wipro's operating margin in FY2025-26", the follow-up "and 24-25" got the reply "Year-on-year
    #      change of which figure?". The model had labelled it "yoy" because a second year was mentioned in the
    #      conversation. A year-on-year question is now recognised only by the question's own words: two years,
    #      or a change word. Otherwise the model's "yoy" is ignored and the question is a plain fact or ratio.
    elif says_yoy:                                    # same test as above, now kept in one place (YOY_WORDS)
        intent = "yoy"
    elif intent in ("other", "yoy"):
        intent = "ratio" if metric else "fact"
    if len(tickers) > 1 and intent in ("fact", "ratio"):
        intent = "compare_rank"
    if intent == "yoy":
        if metric and metric != "yoy_change" and not item:
            raise Clarify("I can give the year-on-year change of a reported figure such as revenue or net profit. Which one?")
        metric = "yoy_change"

    if not tickers:
        raise Clarify("Which company do you mean?")
    banks = [bool(get_company_profile(t)["is_bank"]) for t in tickers]
    if metric in not_for_banks() and any(banks):
        raise Clarify(f"{metric.replace('_', ' ').capitalize()} is not a meaningful measure for a bank. "
                      "Would you like the capital adequacy ratio, gross NPA ratio, net interest margin or cost-to-income instead?")
    if metric in bank_only_metrics() and not all(banks):
        raise Clarify(f"{metric.replace('_', ' ').capitalize()} applies to banks only. "
                      "Would you like operating margin, net profit margin or return on equity instead?")
    applies = _item_applies(item) if item else None
    if applies and intent != "summary" and any((applies == "bank") != b for b in banks):
        nice = item.replace("_", " ").capitalize()
        if applies == "bank":
            raise Clarify(f"'{nice}' is a bank statement line and this company is not a bank. "
                          "Would you like total expenses, employee benefits expense or finance costs instead?")
        raise Clarify(f"'{nice}' is not a line in a bank's statements. "
                      "Would you like interest earned, total income, operating expenses or net profit instead?")
    if intent != "summary" and re.search(r"\bmargin\b", q) and not metric:
        raise Clarify("Which margin do you mean: operating margin or net profit margin?")
    if intent != "summary" and not metric and not item:
        raise Clarify("Which figure or ratio would you like (for example revenue, net profit or operating margin)?")
    if intent == "compare_rank" and len(tickers) < 2:
        raise Clarify("Which companies should I compare?")

    # fiscal years
    from_model = [y for y in (plan.fiscal_years if not follow else []) if y in years_corpus]
    years = years_in(question) or from_model or (memory.get("fiscal_years", []) if follow else [])
    if not years:
        raise Clarify("Which fiscal year, " + " or ".join(fy_label(y) for y in years_corpus) + "?")
    years = sorted(set(years))
    if intent == "yoy":
        if len(years) == 1:
            years = [previous_year(years[0]), years[0]]
        if years[-1] not in years_corpus:
            raise Refuse("not_in_corpus", f"{fy_label(years[-1])} is not in my corpus.")
        years = years[-2:]
        if not item:
            raise Clarify("Year-on-year change of which figure (for example revenue or net profit)?")
    else:
        years = [y for y in years if y in years_corpus][-1:]
        if not years:
            raise Refuse("not_in_corpus", "That fiscal year is not in my corpus. I cover "
                         + " and ".join(fy_label(y) for y in years_corpus) + ".")

    scope = "standalone" if "standalone" in q else "consolidated" if "consolidated" in q else \
        (memory.get("scope") if follow else None) or plan.scope or DEFAULT_SCOPE
    if metric and metric_kind(metric) == "reported" and all(banks) and "consolidated" not in q:
        scope = "standalone"                      # banks report these ratios for the bank itself
    order = "lowest" if re.search(r"\b(lowest|lower|least|smallest|worst)\b", q) else "highest"
    return AgentPlan(intent=intent, companies=tickers, fiscal_years=years, scope=scope, metric=metric, item=item,
                     topic=plan.topic or question, order=order, is_follow_up=follow)


def build_steps(plan: AgentPlan) -> list[AgentStep]:
    """One step per company (find its inputs and compute its value), then one comparison step if needed."""
    if plan.intent == "summary":
        return [AgentStep(tool="summarise", args={"company": plan.companies[0], "fiscal_year": plan.fiscal_years[-1],
                                                  "topic": plan.topic})]
    steps = [AgentStep(tool="value_for_company", args={"company": c}) for c in plan.companies]
    if plan.intent == "compare_rank":
        steps.append(AgentStep(tool="compare_rank", args={"order": plan.order}))
    return steps
