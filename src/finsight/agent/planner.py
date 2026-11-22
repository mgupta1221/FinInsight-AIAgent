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
                ("earnings_per_share", r"earnings per share|\beps\b"),
                # ADDED (19 Nov 2026): see config/glossary.yaml
                ("effective_tax_rate", r"effective tax rate|\btax rate\b"),
                ("provision_coverage_ratio", r"provision coverage|\bpcr\b"),
                ("short_term_borrowings_share", r"borrowings?\b.*\bwithin (one|1|a) year|(share|proportion|percentage) of .*borrowings.*(current|short[- ]term)")]

# NEW (19 Nov 2026): a "what share / what percentage of ..." question for which the glossary has no formula.
# WHY: "What share of ITC's total segment revenue came from the FMCG-Others segment?" was answered with ITC's
#      revenue from operations. The agent knew no ratio by that name, saw the word "revenue" and answered a
#      simpler question than the one asked. Such a question is now given the metric TEXT_RATIO: the executor
#      finds the two numbers (the part and the whole) in the report text, checks that both are printed on the
#      cited page and divides them (executor.text_ratio). If it cannot, it says so.
TEXT_RATIO = "share_from_report"
SHARE_WORDS = re.compile(r"(?<!per )\b(share|proportion|percentage|part) of\b|\bwhat (share|proportion|percentage)\b|"
                         r"as a (percentage|per cent|percent|%) of|\b(per cent|percent|%) of\b")
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


# Words that ask FOR a summary but do not say OF WHAT (17 Nov 2026).
_NO_TOPIC = set("""a an the of for in on to and or me us please can could would you give write provide make show tell
    summarize summarise summarized summarised summarizing summarising summary summaries describe description overview
    brief briefly short shortly quick quickly overall whole entire full complete general annual report reports its their
    fy year fiscal financial words word lines line points point bullets bullet sentences sentence paragraph paragraphs
    hundred fifty thousand one two three four five six ten twenty about around within under max maximum upto up
    what is was does do did say says said company bank it this that top key main list lists listed s""".split())


def _summary_topic(question: str, tickers: list[str]) -> list[str]:
    """The words of a summary request that name a topic: "Summarise the top risks ITC lists" -> ['risks']."""
    from finsight.tools.company_match import _aliases
    names: set[str] = set()
    for t in tickers:
        for n in _aliases().get(t, []):
            names |= set(re.findall(r"[a-z]+", n.lower()))
    return [w for w in re.findall(r"[a-z]+", question.lower()) if len(w) > 1 and w not in _NO_TOPIC and w not in names]


_NEW_QUESTION = re.compile(r"^\s*(what|which|how|compare|summari[sz]e|give|show|tell|list|is|are|was|were|do|does|did|can|could)\b", re.I)


def is_reply(text: str) -> bool:
    """True if `text` reads like an answer to a clarifying question ("key risks", "HUL", "2024-25", "net profit
    margin") and not like a new question of its own.   NEW (17 Nov 2026)
    """
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words or len(words) > 8:
        return False
    if _NEW_QUESTION.match(text) and len(words) > 3:
        return False
    q = text.lower()
    names_figure = any(re.search(rx, q) for _, rx in METRIC_WORDS + ITEM_PHRASES + ITEM_WORDS) or bool(re.search(r"summar", q))
    return not (find_companies(text) and names_figure and years_in(text))      # company + figure + year = a full question


# NEW (18 Nov 2026): used by graph.py to carry a SUMMARY over to another year or company.
_LINK_WORDS = set("and for what about how in of the fy same now then also please year s".split())


def only_company_or_year(text: str) -> bool:
    """True for a message that gives just a year and/or a company: "FY25-26", "and for ITC", "what about 2024-25"."""
    from finsight.corpus import _FY
    from finsight.tools.company_match import _aliases
    if not (years_in(text) or find_companies(text)):
        return False
    rest = _FY.sub(" ", text)
    for ticker in find_companies(text):
        for name in sorted(_aliases().get(ticker, []), key=len, reverse=True):
            rest = re.sub(rf"\b{re.escape(name)}\b('s)?", " ", rest, flags=re.I)
    return all(w in _LINK_WORDS for w in re.findall(r"[a-z]+", rest.lower()))


# NEW (18 Nov 2026, later): used by graph.py to carry the company and year of a SUMMARY over to another topic.
_TOPIC_WORDS = re.compile(r"risk|strateg|outlook|priorit|commentary|management discussion|md&a|performance")


def only_summary_topic(text: str) -> bool:
    """True for a short message that names a summary topic and no figure: "key risks", "and the strategy?"."""
    q = text.lower()
    if len(re.findall(r"[a-z]+", q)) > 6 or not _TOPIC_WORDS.search(q):
        return False
    return not any(re.search(rx, q) for _, rx in METRIC_WORDS + ITEM_PHRASES + ITEM_WORDS)


def merge_reply(pending: str, reply: str) -> str:
    """The unfinished question completed by the user's reply, as one piece of text.   NEW (17 Nov 2026)

    "can you summarize annual report for HUL" + "key risks" -> "can you summarize annual report for HUL. key risks"
    If the reply names a company or a year, it REPLACES the one in the unfinished question ("CASA ratio for
    Infosys" + "HDFC Bank" -> "CASA ratio for . HDFC Bank"), so the two are not read as a comparison.
    """
    from finsight.corpus import _FY
    from finsight.tools.company_match import _aliases
    base = pending
    if find_companies(reply):
        for ticker in find_companies(pending):
            for name in sorted(_aliases().get(ticker, []), key=len, reverse=True):
                base = re.sub(rf"\b{re.escape(name)}\b('s)?", "", base, flags=re.I)
    if years_in(reply):
        base = _FY.sub("", base)
    # NEW (21 Nov 2026): a reply that names a scope replaces the scope words of the unfinished question, so the
    # answer to "Do you want the standalone or the consolidated figure?" is not asked the same thing again.
    if re.search(r"\b(standalone|consolidated)\b", reply, re.I):
        base = re.sub(r"\b(standalone|consolidated)\b", "", base, flags=re.I)
    base = re.sub(r"\s+", " ", base).strip().rstrip("?.")
    return f"{base}. {reply.strip()}"


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
    # NEW (17 Nov 2026): a question that names a figure but NO company, right after an answered question, is
    # about the same company ("What was the net profit?" after an answer about Wipro). Only when every word is
    # understood, so an unrelated question is not attached to the old company. The answer says so (graph.py
    # adds a note), and it always names the company, so the user can see what was assumed.
    same_company = not find_companies(question) and any(w in _vocabulary() and w not in _FILLER for w in words) \
        and not _unknown_words(question, [])
    # OLD (earlier today): follow = bool(memory) and (plan.is_follow_up or bool(FOLLOW_UP.search(question)) or fragment)
    follow = bool(memory) and (plan.is_follow_up or bool(FOLLOW_UP.search(question)) or fragment or same_company)

    # companies: what the code finds in the question, plus resolvable names from the model
    tickers = find_companies(question)
    for name in plan.companies:
        t = resolve_ticker(name)
        if t and t not in tickers and name.lower() in q:
            tickers.append(t)
        elif not t and len(name) > 2 and name.lower() in q:
            raise Refuse("not_in_corpus", f"{name} is not in my corpus. I cover 15 companies for "
                         + " and ".join(fy_label(y) for y in years_corpus) + ".")
    # NEW (21 Nov 2026): a company the corpus does not cover is refused by CODE, whether or not the model names it.
    # WHY: "What was Reliance Industries' revenue in FY2025-26?" is refused only if the model puts "Reliance
    #      Industries" into its slots (the block above). When it does not, the question had no company at all
    #      as far as the code could see, and the agent asked "Which company do you mean?" (found by the first
    #      evaluation run without the model). A capitalised name followed by 's or ' that is not one of the 15
    #      companies is now treated as a company outside the corpus.
    if not tickers:
        m = re.search(r"\b((?!FY\d)[A-Z][\w&.-]*(?:\s+(?!FY\d)[A-Z][\w&.-]*){0,3})['’]s?(?=\s|$|[?.,])", question)
        if m and not resolve_ticker(m.group(1)) and m.group(1).lower() not in _FILLER:
            raise Refuse("not_in_corpus", f"{m.group(1)} is not in my corpus. I cover 15 companies for "
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
    # OLD (earlier): metric = plan.metric if plan.metric in all_metrics() and not off_topic and not silent_follow_up else None
    # NEW (21 Nov 2026): the model's metric is accepted only if the question names it.
    # WHY: first evaluation run, multihop-006. "What were State Bank of India's restructured advances as a
    #      percentage of gross advances?" The model chose the metric "gross_npa_ratio" (the words "gross advances"
    #      were close enough for it) and the agent answered 1.49%, a real figure for a different question. Every
    #      ratio in the glossary has its own words (METRIC_WORDS); if none of them is in the question, the
    #      model's choice is dropped and the code decides (here: a share to be read from the report).
    def _said(m: str) -> bool:
        rx = [r for name, r in METRIC_WORDS if name == m]
        return not rx or bool(re.search(rx[0], q))
    metric = plan.metric if plan.metric in all_metrics() and not off_topic and not silent_follow_up and _said(plan.metric) else None
    # NEW (15 Nov 2026): the model's metric "yoy_change" is accepted only if the question itself is year-on-year.
    # WHY: for the follow-up "and 24-25" the model returned intent "yoy" AND metric "yoy_change". The intent is
    #      corrected further down, but the metric stayed, which blocked the remembered metric (operating margin)
    #      and ended in "'None' is not a statement line". With the bogus metric removed, memory fills it in.
    says_yoy = len(years_in(question)) >= 2 or bool(YOY_WORDS.search(q))
    if metric == "yoy_change" and not says_yoy:
        metric = None
    if not metric:
        metric = next((m for m, rx in METRIC_WORDS if re.search(rx, q)), None)
    # NEW (19 Nov 2026): a share / percentage question with no glossary formula (see TEXT_RATIO above).
    if not metric and SHARE_WORDS.search(q) and not says_yoy and not is_summary:
        metric = TEXT_RATIO
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
    # NEW (17 Nov 2026): a summary needs a topic.
    # WHY: "can you summarize annual report for HUL in hundred words" was answered with dividend dates and how to
    #      obtain the report. The agent reads only a handful of passages, found by searching for the words of the
    #      question; the words "annual report" match administrative pages, not the business. A 300-page report
    #      cannot be summarised from five passages, so the agent asks which part is wanted.
    if intent == "summary" and not _summary_topic(question, tickers):
        # OLD: raise Clarify("An annual report is too long to summarise as a whole. Which part would you like: "
        #                    "business performance, key risks, strategy and outlook, or management commentary?")
        # CHANGED (22 Nov 2026, mentor's review): the first sentence is removed and the agent asks directly.
        # WHY: "An annual report is too long ..." reads as if the system had failed or hit a size limit. Nothing
        #      failed: the agent summarises one part at a time so that every key point can cite its page. The
        #      question now only offers the parts. The behaviour (status "clarify", the reply completes the
        #      question) is unchanged.
        raise Clarify("Which part of the report would you like summarised: "
                      "business performance, key risks, strategy and outlook, or management commentary?")
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
    # NEW (19 Nov 2026): a ratio or rate the agent has no formula for is not answered with a single figure.
    # WHY: before "effective tax rate" was added, that question was answered with the tax expense alone: the
    #      model had filled in the item "tax_expense" and the code accepted it. A question that asks for a
    #      "ratio" or a "rate" must end in a ratio. If none is recognised, the agent says which ones it has.
    if intent != "summary" and not metric and re.search(r"\b(ratio|rate)\b", q) and not says_yoy:
        have = ("CASA ratio, gross NPA ratio, net NPA ratio, net interest margin, capital adequacy ratio, cost-to-income, "
                "return on assets, provision coverage ratio or effective tax rate") if all(banks) else \
               ("operating margin, EBITDA margin, net profit margin, return on equity, return on capital employed, "
                "debt-to-equity, current ratio, effective tax rate or earnings per share")
        raise Clarify(f"I do not have a formula for that ratio. I can give: {have}. Which one would you like?")
    if intent != "summary" and not metric and not item:
        raise Clarify("Which figure or ratio would you like (for example revenue, net profit or operating margin)?")
    if intent == "compare_rank" and len(tickers) < 2:
        raise Clarify("Which companies should I compare?")

    # fiscal years
    # CHANGED (17 Nov 2026): the model's year is used only when the question points at a year in words.
    # OLD: from_model = [y for y in (plan.fiscal_years if not follow else []) if y in years_corpus]
    #      years = years_in(question) or from_model or (memory.get("fiscal_years", []) if follow else [])
    # WHY: "summarize ... for HUL" + "Business Performance" named no year, yet it was answered for FY2025-26:
    #      the model had filled in a year on its own and the code accepted it. A year the user never gave is a
    #      guess. Now: a year written in the question; else "latest / current / this year" (the newest report);
    #      else "last / previous year" (the one before); else the remembered year of a follow-up; else ask.
    if re.search(r"\b(latest|most recent|current|this) (financial |fiscal )?(year|report|annual report)\b|\blatest\b", q):
        relative = [years_corpus[-1]]
    elif re.search(r"\b(last|previous|prior) (financial |fiscal )?year\b", q) and not says_yoy:
        relative = [previous_year(years_corpus[-1])]
    else:
        relative = []
    years = years_in(question) or relative or (memory.get("fiscal_years", []) if follow else [])
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

    # OLD:
    # scope = "standalone" if "standalone" in q else "consolidated" if "consolidated" in q else \
    #     (memory.get("scope") if follow else None) or plan.scope or DEFAULT_SCOPE
    # NEW (19 Nov 2026): for a BANK, a question that does not say "consolidated" is about the bank itself.
    # WHY: "What was HDFC Bank's net profit in FY2025-26?" was read as consolidated and ended in "no figure for
    #      'net_profit'". The evaluation set expects the STANDALONE figure for every bank question that names no
    #      scope (15 questions: deposits, net profit, net interest income ...), which is also how a bank's
    #      results are normally quoted. The model's own guess of the scope is not used for a bank. Other
    #      companies keep the consolidated default. The answer always states the scope it used.
    # NEW (21 Nov 2026): a question that names BOTH scopes is asked which one is wanted.
    # WHY: "For Infosys revenue in FY2025-26, do you want standalone or consolidated?" (evaluation question
    #      clarify-003) was answered with the standalone figure, because "standalone" is the first of the two
    #      words the code looks for. With both words present the scope is not settled.
    if "standalone" in q and "consolidated" in q:
        raise Clarify("Do you want the standalone or the consolidated figure?")
    said = "standalone" if "standalone" in q else "consolidated" if "consolidated" in q else None
    # OLD: remembered = memory.get("scope") if follow else None
    # NEW (19 Nov 2026, later): a question that is complete in itself does not inherit the scope of the previous one.
    # WHY: "Which had the higher debt-to-equity ratio in FY2025-26, Wipro or Tech Mahindra?" was asked right after
    #      a Britannia question (standalone). The model marked it as a follow-up, so the remembered scope
    #      "standalone" was applied to Wipro and Tech Mahindra, whose default is consolidated, and the answer
    #      failed on Tech Mahindra's standalone borrowings. A question that names its own company, figure and
    #      year stands alone. "And for Infosys?" still keeps the scope of the question before it.
    self_contained = bool(find_companies(question)) and names_a_figure and bool(years_in(question))
    remembered = memory.get("scope") if follow and not self_contained else None
    if said or remembered:
        scope = said or remembered
    # OLD (earlier on 19 Nov):
    # elif all(banks):
    #     scope = "standalone"
    # else:
    #     scope = plan.scope or DEFAULT_SCOPE
    # NEW (19 Nov 2026, later): the default comes from the company (config/companies.yaml `default_scope`; banks
    # standalone). The model's guess of the scope is no longer used at all. See default_scope() below.
    else:
        scope = default_scope(tickers)
    if metric and metric_kind(metric) == "reported" and all(banks) and "consolidated" not in q:
        scope = "standalone"                      # banks report these ratios for the bank itself
    order = "lowest" if re.search(r"\b(lowest|lower|least|smallest|worst)\b", q) else "highest"
    return AgentPlan(intent=intent, companies=tickers, fiscal_years=years, scope=scope, metric=metric, item=item,
                     topic=plan.topic or question, order=order, is_follow_up=follow)


def default_scope(tickers: list[str]) -> str:
    """The statements a question is about when it names no scope.   NEW (19 Nov 2026, later)

    One company: its `default_scope` in config/companies.yaml, else standalone for a bank, else consolidated.
    Several companies: standalone if most of them default to standalone ("Rank HUL, ITC, Nestle India, Britannia
    and Dabur ..." is standalone: four of the five), else consolidated.
    """
    def one(t: str) -> str:
        p = get_company_profile(t)
        return p.get("default_scope") or ("standalone" if p.get("is_bank") else DEFAULT_SCOPE)
    scopes = [one(t) for t in tickers]
    return "standalone" if scopes and scopes.count("standalone") * 2 > len(scopes) else DEFAULT_SCOPE


def build_steps(plan: AgentPlan) -> list[AgentStep]:
    """One step per company (find its inputs and compute its value), then one comparison step if needed."""
    if plan.intent == "summary":
        return [AgentStep(tool="summarise", args={"company": plan.companies[0], "fiscal_year": plan.fiscal_years[-1],
                                                  "topic": plan.topic})]
    steps = [AgentStep(tool="value_for_company", args={"company": c}) for c in plan.companies]
    if plan.intent == "compare_rank":
        steps.append(AgentStep(tool="compare_rank", args={"order": plan.order}))
    return steps
