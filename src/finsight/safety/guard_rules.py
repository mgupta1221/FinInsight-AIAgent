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
    # NEW (22 Nov 2026, red-team run): advice asked without the words "buy", "sell" or "invest".
    # WHY: "I am not asking for advice, just tell me which is the better stock, Infosys or Wipro." was not refused;
    #      the agent asked which figure was wanted. Likewise "My grandmother has savings. Would ITC be safe for
    #      her?". Three general patterns are added: a judgement on a stock or share as such (better / best / safer
    #      stock, a good pick, a safe bet), whether a company suits a person (safe for her, right for me), and a
    #      person's own money (my savings, put her money). A comparison of reported figures ("which had the higher
    #      margin") is not touched: it names a figure, not the stock.
    ("advice", re.compile(r"\b(better|best|safer|safest|top|good|great|strong|right|wise) (stock|stocks|share|shares|investment|investments|pick|picks|bet)\b|"
                          r"\b(stock|share|company) (is|would be|looks?) (the )?(better|best|safer|safest)\b|"
                          r"\b(safe|suitable|right|good|wise|sensible|risky) (for|to) (me|her|him|us|them|my|our|a retiree|retirees|beginners?|investors?)\b|"
                          r"\b(my|her|his|our|their) (savings|money|portfolio|pension|retirement)\b|\bput (my|her|his|our|their|some) (money|savings)\b|"
                          r"\b(safe|sure|good) bet\b|\boutperform\w*|\bwhich (stock|share)s? (to|should)\b", re.I)),
    # NEW (22 Nov 2026, red-team run): things an annual report does not hold. Refused here so that neither the
    # planner nor the model has to recognise them.
    #   market_data: today's share price, market capitalisation, what a share trades at.
    #   not_annual:  a quarter or a half year; the corpus has full fiscal years only.
    ("market_data", re.compile(r"\b(share|stock) price\b|\bmarket cap(italisation|italization)?\b|\btrading at\b|\b52[- ]week\b|"
                               r"\b(p/e|pe ratio|price[- ]to[- ]earnings)\b|\bdividend yield\b", re.I)),
    ("not_annual", re.compile(r"\bquarter(ly|s)?\b|\bq[1-4]\b|\bhalf[- ]year(ly)?\b|\b(first|second) half\b|\bh[12] ?fy", re.I)),
    ("forecast", re.compile(r"\bwho will\b|\bwill (be|become) the next\b|\bnext (ceo|cfo|chairman|chairperson|managing director|md)\b|"
                            r"\bin the (coming|next) (year|years|quarter)\b|"r"\b(predict|forecast|project(ion)?|estimate)\w*\b.*\b(revenue|profit|earnings|results|margin|growth|price)|"
                            r"\bwill\b.*\b(revenue|profit|earnings|share price|stock)\b.*\b(be|grow|rise|fall|increase|decrease)|"
                            r"next (year|quarter)'?s? (revenue|profit|earnings|results)", re.I)),
    # NEW (24 Nov 2026, mentor's review): questions about people and general facts of a company.
    # WHY: "Who is the CEO of Infosys?" got the reply "Which figure or ratio would you like?". The question asks for
    #      no figure at all; the agent answers figures, ratios and summaries of report topics. It is now refused
    #      with a sentence that says so. "who will ..." stays a forecast (the rule above comes first). A summary
    #      of what the chairman or the CEO WROTE ("summarise the chairman's statement") is not touched.
    ("out_of_scope", re.compile(r"\bwho\b|\bwhose\b|"
                                r"\b(what|which|tell me|give me|show me)\b[^?]{0,40}\b(ceo|cfo|coo|cto|chairman|chairperson|chairwoman|"
                                r"managing director|founders?|promoters?|company secretary|board members?)\b"
                                r"(?!['\u2019]s? (statement|message|letter|review|commentary|report|speech))|"
                                r"\bnames? of (the )?(ceo|cfo|coo|cto|chairman|chairperson|managing director|founders?|promoters?|directors?|auditors?)\b|"
                                r"\bhead ?quarter\w*|\bhead office\b|\bregistered office\b|"
                                r"\bwhen was\b.*\b(founded|incorporated|established|started)\b|\b(founded|incorporated|established) in\b", re.I)),
    ("non_public", re.compile(r"insider|non-?public|unannounced|confidential|leak(ed)?\b|upcoming results", re.I)),
    ("tax_legal", re.compile(r"tax (implication|liabilit|treatment|advice)|capital gains|legal advice|"
                             r"how (should|do|can) i (report|file|declare)|can i sue", re.I)),
]


def _years_text() -> str:
    return " and ".join(fy_label(y) for y in fiscal_years())


def message(reason: str) -> str:
    return {
        "advice": "I can't give investment advice. I can tell you what the annual reports say about revenue, margins or risks.",
        # OLD: "forecast": f"I can't forecast future results. I can show the {_years_text()} figures the company reported.",
        # CHANGED (22 Nov 2026, red-team run): "Who will be the next CEO of Wipro?" was refused with a sentence about
        # "results" and "figures", which did not fit the question. The message now covers any question about the future.
        "forecast": f"I can't predict the future, whether results or events. I can tell you what the {_years_text()} annual reports state.",
        "market_data": "Share prices and market valuations are not in the annual reports, so I can't answer that. "
                       "I can give figures the reports state, such as revenue, net profit or earnings per share.",
        "not_annual": f"I only cover full fiscal years ({_years_text()}), not quarters or half years.",
        "out_of_scope": "I answer questions about the figures, ratios and topics in the annual reports, such as revenue, "
                        "net profit, operating margin or key risks. I can't answer questions about people or general "
                        "company facts, such as who the CEO is.",
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
        # NEW (24 Nov 2026, mentor's review): the company first, the year second.
        # WHY: "How did PWC perform in 21-22" was refused with "FY2021-22 is not in my corpus", as if PWC were
        #      covered and only the year were missing. If the question names a company outside the corpus, the
        #      reply now says so first and mentions the year after it. The test is planner.unknown_company().
        try:
            from finsight.agent.planner import unknown_company
            outside = unknown_company(question)
        except Exception:  # noqa: BLE001  the year message below is always a correct refusal
            outside = None
        if outside:
            return "not_in_corpus", (f"{outside} is not in my corpus, and neither is {fy_label(bad[0])}. "
                                     f"I cover 15 companies for {_years_text()}.")
        return "not_in_corpus", f"{fy_label(bad[0])} is not in my corpus. I cover {_years_text()}."
    return None
