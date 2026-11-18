"""End-to-end tests of the agent loop with a scripted model, a made-up figure store and fixed search results.

NEW FILE (agent layer, 13 Nov 2026). No network, no PDFs, no Qdrant. Numbers are invented (see conftest.py).
"""
import pytest

from conftest import model
from finsight.agent.memory import Memory

Q_REV = "What was Infosys' consolidated revenue from operations in FY2025-26?"


def test_refusal_needs_no_model_call(ask):
    llm = model()
    a = ask("Should I buy TCS shares?", llm)
    assert a.status == "refused" and a.refusal_reason == "advice" and llm.calls == [] and a.tokens_used == 0


@pytest.mark.parametrize("q", ["What was revenue last year?", "What was the operating margin?", "Compare the two companies.",
                               "What was the profit?", "What was Infosys' margin in FY2025-26?"])
def test_clarify_when_slots_are_missing(ask, q):
    a = ask(q)
    assert a.status == "clarify" and a.clarifying_question


def test_wrong_kind_of_metric_or_line_gets_an_explanation(ask):
    assert "not a meaningful measure for a bank" in ask("What is the debt-to-equity ratio of HDFC Bank in FY2025-26?").clarifying_question
    assert "applies to banks only" in ask("What was Infosys' CASA ratio in FY2025-26?").clarifying_question
    assert "bank statement line" in ask("What were Infosys' operating expenses in FY2025-26?").clarifying_question


def test_company_outside_corpus_is_refused(ask):
    a = ask("What was Reliance Industries' revenue in FY2025-26?", model(plan={"intent": "fact", "companies": ["Reliance Industries"]}))
    assert a.status == "refused" and a.refusal_reason == "not_in_corpus"


def test_fact_with_citation_and_trace(figure_store, ask):
    a = ask(Q_REV)
    assert a.status == "answered" and a.verified and a.value == 1000.0 and a.unit == "crore"
    assert a.citations == ["INFY-FY2526-p287"] and any(t.get("tool") == "get_financial_item" for t in a.trace)


def test_exact_phrase_beats_the_models_wrong_item(figure_store, ask):
    a = ask("What was Infosys total expenses in FY2025-26?", model(plan={"intent": "fact", "item": "operating_expenses"}))
    assert a.status == "answered" and a.value == 810.0


def test_ratio_uses_the_glossary_formula_through_a_derived_input(figure_store, ask):
    a = ask("What was Infosys' operating margin in FY2025-26?")
    assert a.status == "answered" and a.formula == "ebit / revenue_from_operations * 100"
    assert a.value == pytest.approx((240 + 10 - 50) / 1000 * 100)                      # ebit = PBT + finance costs - other income
    assert {f.name for f in a.inputs} == {"profit_before_tax", "finance_costs", "other_income", "revenue_from_operations"}


def test_yoy_reads_both_years_from_the_later_report(figure_store, ask):
    a = ask("How did Infosys' consolidated revenue from operations change from FY2024-25 to FY2025-26?")
    assert a.status == "answered" and a.value == pytest.approx(11.1111, abs=0.01)
    assert {f.citation for f in a.inputs} == {"INFY-FY2526-p287"}


def test_units_are_converted_before_comparing(figure_store, ask):
    a = ask("Which had higher consolidated revenue from operations in FY2025-26, Infosys or Tech Mahindra?")   # crore vs million
    assert a.status == "answered" and a.ranking == ["INFY", "TECHM"] and a.answer_company == "INFY"


def test_bank_metric_from_statement_lines_in_thousands(figure_store, ask):
    a = ask("What was SBI's standalone cost-to-income ratio in FY2025-26?")
    assert a.status == "answered" and a.value == pytest.approx(1000000 / (4000000 - 2500000 + 500000) * 100)


def test_unconfirmed_unit_escalates_instead_of_guessing(figure_store, ask):
    a = ask("What was HDFC Bank's standalone net profit in FY2025-26?")
    assert a.status == "escalated" and a.value is None and "HDFCBANK-FY2526-p354" in a.answer


def test_missing_figure_escalates(figure_store, ask):
    assert ask("What was Wipro's consolidated net profit in FY2025-26?").status == "escalated"


def test_critic_rejects_invented_number_and_falls_back_to_template(figure_store, ask):
    a = ask(Q_REV, model(draft={"answer": "Infosys' revenue was about ₹2,000 crore in FY2025-26, a strong result."}))
    assert a.status == "answered" and "1,000.00" in a.answer and "2,000" not in a.answer
    assert [t["ok"] for t in a.trace if t.get("node") == "critic"] == [False, False, True]


def test_follow_up_uses_memory(figure_store, ask):
    mem = Memory(":memory:")
    ask(Q_REV, mem=mem)
    a = ask("And for FY2024-25?", mem=mem)
    assert a.status == "answered" and a.companies == ["INFY"] and a.fiscal_years == ["2024-25"] and a.value == 900.0


def test_reported_ratio_is_verified_against_the_page(fake_search, ask):
    good = {"found": True, "value": 34.8, "quote": "34.8", "citation": "HDFCBANK-FY2425-p210"}
    a = ask("What is the HDFC Bank CASA ratio in FY2024-25?", model(extracted=good))
    assert a.status == "answered" and a.value == 34.8 and a.scope == "standalone" and a.citations == ["HDFCBANK-FY2425-p210"]
    invented = {"found": True, "value": 41.2, "quote": "41.2", "citation": "HDFCBANK-FY2425-p210"}
    assert ask("What is the HDFC Bank CASA ratio in FY2024-25?", model(extracted=invented)).status == "escalated"
    header_digits = {"found": True, "value": 210, "quote": "210", "citation": "HDFCBANK-FY2425-p210"}   # 210 is only in the chunk header
    assert ask("What is the HDFC Bank CASA ratio in FY2024-25?", model(extracted=header_digits)).status == "escalated"


def test_summary_sanitises_and_checks_citations(fake_search, ask):
    good = {"answer": "ITC lists three risks.", "key_points": [{"point": p, "citation": "[ITC-FY2526-p110]"}
            for p in ("Cyber security risk", "Commodity price risk", "Regulatory risk")]}
    a = ask("Summarise the top risks ITC lists in its FY2025-26 report.", model(summary=good))
    assert a.status == "answered" and a.verified and any("sanitiser" in t.get("note", "") for t in a.trace)
    bad = {**good, "key_points": [{**k, "citation": "ITC-FY2526-p999"} for k in good["key_points"]]}
    assert ask("Summarise the top risks ITC lists in its FY2025-26 report.", model(summary=bad)).status == "escalated"


# ---- added 15 Nov 2026 ----
def test_new_question_is_not_answered_from_memory(figure_store, ask):
    """After a net-profit question, an unrelated question about the same company must not repeat net profit,
    even if the model marks it as a follow-up and copies the old item."""
    mem = Memory(":memory:")
    assert ask("What was Infosys' consolidated net profit in FY2025-26?", mem=mem).value == 180.0
    copycat = model(plan={"intent": "fact", "companies": ["Infosys"], "item": "net_profit", "is_follow_up": True})
    a = ask("What is the dress code at Infosys?", copycat, mem=mem)
    assert a.status == "clarify" and a.value is None
    a = ask("What is best price to buy Infosys?", copycat, mem=mem)
    assert a.status == "refused" and a.refusal_reason == "advice"


def test_real_follow_ups_still_use_memory(figure_store, ask):
    mem = Memory(":memory:")
    ask(Q_REV, mem=mem)
    assert ask("and for 24-25", mem=mem).value == 900.0                                  # year only
    mem2 = Memory(":memory:")
    ask(Q_REV, mem=mem2)
    assert ask("And what about the standalone figure?", mem=mem2).value == 800.0         # scope only (year kept)
    a = ask("and for Tech Mahindra in FY2025-26", mem=mem)                                # company + year, item kept
    assert a.status == "answered" and a.companies == ["TECHM"] and a.value == 500.0     # 5,000 million = 500 crore
    flagged = model(plan={"intent": "fact", "is_follow_up": True})
    assert ask("What about its net profit?", flagged, mem=mem).value == 40.0             # new item, company and year kept
    copied = model(plan={"intent": "fact", "item": "net_profit", "is_follow_up": True})
    assert ask("and its revenue?", copied, mem=mem).value == 500.0                       # the word in the question beats a copied item


def test_model_cannot_turn_a_year_follow_up_into_year_on_year(figure_store, ask):
    """Real run, 15 Nov 2026: "and 24-25" after an operating-margin question was treated as a yoy question."""
    mem = Memory(":memory:")
    ask(Q_REV, mem=mem)
    wrong = model(plan={"intent": "yoy", "is_follow_up": True})
    a = ask("and 24-25", wrong, mem=mem)
    assert a.status == "answered" and a.intent == "fact" and a.value == 900.0 and a.fiscal_years == ["2024-25"]
    mem = Memory(":memory:")                                    # second real run: the model also sent metric "yoy_change"
    ask(Q_REV, mem=mem)
    worse = model(plan={"intent": "yoy", "metric": "yoy_change", "is_follow_up": True})
    a = ask("and 24-25", worse, mem=mem)
    assert a.status == "answered" and a.intent == "fact" and a.value == 900.0
    from finsight.agent.planner import resolve
    from finsight.schemas import AgentPlan
    kept = {"companies": ["WIPRO"], "fiscal_years": ["2025-26"], "scope": "consolidated", "metric": "operating_margin", "item": None}
    plan = resolve(AgentPlan(intent="yoy", metric="yoy_change", is_follow_up=True), "and 24-25", kept)
    assert (plan.intent, plan.metric, plan.fiscal_years, plan.companies) == ("ratio", "operating_margin", ["2024-25"], ["WIPRO"])
    guess = AgentPlan(intent="ratio", metric="net_profit_margin", item="net_profit", is_follow_up=True)     # any guess is ignored
    for q, year, company in (("and 24-25", "2024-25", "WIPRO"), ("and for Infosys", "2025-26", "INFY"), ("24-25?", "2024-25", "WIPRO")):
        plan = resolve(guess, q, kept)
        assert (plan.metric, plan.item, plan.fiscal_years, plan.companies) == ("operating_margin", None, [year], [company]), q
    for q, year, company in (("24-25?", "2024-25", "WIPRO"), ("Infosys?", "2025-26", "INFY"), ("FY2024-25", "2024-25", "WIPRO")):
        plan = resolve(AgentPlan(intent="other"), q, kept)                        # the model did not flag a follow-up
        assert (plan.metric, plan.fiscal_years, plan.companies) == ("operating_margin", [year], [company]), q
    plan = resolve(AgentPlan(intent="ratio", metric="net_profit_margin", is_follow_up=True), "and the net profit margin?", kept)
    assert plan.metric == "net_profit_margin"                                    # a figure IS named: the new metric is used
    a = ask("How did Infosys' consolidated revenue from operations in FY2025-26 compare with the previous year?", mem=Memory(":memory:"))
    assert a.status == "answered" and a.intent == "yoy" and a.value == pytest.approx(11.1111, abs=0.01)


def test_summary_without_a_topic_asks_which_part(fake_search, ask):
    """Real run, 17 Nov 2026: "summarize annual report for HUL" was answered with dividend dates."""
    for q in ("can you summarize annual report for HUL in hundred words", "Summarise the ITC FY2025-26 annual report", "Give me a brief summary of ITC"):
        a = ask(q)
        assert a.status == "clarify" and "Which part" in a.clarifying_question, q
    good = {"answer": "ITC lists three risks.", "key_points": [{"point": p, "citation": "ITC-FY2526-p110"} for p in ("Cyber risk", "Commodity risk", "Regulatory risk")]}
    assert ask("Summarise the top risks ITC lists in its FY2025-26 report.", model(summary=good)).status == "answered"


# ---- added 17 Nov 2026: replies to a clarifying question ----
def test_reply_to_a_clarifying_question_completes_it(figure_store, fake_search, ask):
    """Real run: 'summarize annual report for HUL' -> 'key risks' -> 'HUL' -> 'net profit' asked for the company
    every time, because nothing was kept after a clarifying question."""
    mem = Memory(":memory:")
    good = {"answer": "ITC lists three risks.", "key_points": [{"point": p, "citation": "ITC-FY2526-p110"} for p in ("Cyber risk", "Commodity risk", "Regulatory risk")]}
    a = ask("can you summarize annual report for ITC in hundred words", mem=mem)
    assert a.status == "clarify" and "Which part" in a.clarifying_question
    a = ask("key risks", mem=mem)                                                 # topic given; company is remembered
    assert a.status == "clarify" and "fiscal year" in a.clarifying_question
    a = ask("2025-26", model(summary=good), mem=mem)                              # year given; everything is known now
    assert a.status == "answered" and a.companies == ["ITC"] and len(a.key_points) == 3

    mem = Memory(":memory:")
    assert "Which company" in ask("What was the consolidated revenue from operations?", mem=mem).clarifying_question
    assert "fiscal year" in ask("Infosys", mem=mem).clarifying_question
    a = ask("FY2025-26", mem=mem)
    assert a.status == "answered" and a.value == 1000.0 and any("reply to my clarifying question" in t.get("note", "") for t in a.trace)


def test_a_reply_can_replace_the_company_or_choose_an_option(figure_store, ask):
    mem = Memory(":memory:")
    assert "banks only" in ask("What was Infosys' CASA ratio in FY2025-26?", mem=mem).clarifying_question
    a = ask("operating margin", mem=mem)                                          # picks one of the offered options
    assert a.status == "answered" and a.metric == "operating_margin" and a.companies == ["INFY"]
    mem = Memory(":memory:")
    assert "Which margin" in ask("What was Infosys' margin in FY2025-26?", mem=mem).clarifying_question
    assert ask("net profit margin", mem=mem).metric == "net_profit_margin"
    from finsight.agent.planner import merge_reply
    assert "infosys" not in merge_reply("CASA ratio for Infosys in FY2025-26", "HDFC Bank").lower()       # company replaced
    assert merge_reply("revenue of Wipro in FY2025-26", "2024-25").count("2025-26") == 0                  # year replaced


def test_unfinished_question_is_dropped_by_a_new_question_or_after_one_turn(figure_store, ask):
    mem = Memory(":memory:")
    ask("can you summarize annual report for ITC in hundred words", mem=mem)      # leaves an unfinished question
    a = ask("What was Infosys' consolidated net profit in FY2025-26?", mem=mem)   # a full new question
    assert a.status == "answered" and a.companies == ["INFY"] and a.value == 180.0 and a.intent == "fact"
    assert mem.pop_pending("t") is None
    mem = Memory(":memory:")                                                      # nothing remembered from earlier answers
    ask("can you summarize annual report for ITC in hundred words", mem=mem)
    assert ask("Should I buy ITC shares?", mem=mem).status == "refused"           # a refusal also clears it
    a = ask("key risks", mem=mem)                                                 # too late: this is a new, incomplete question
    assert a.status == "clarify" and "Which company" in a.clarifying_question
    from finsight.agent.planner import is_reply
    assert is_reply("key risks") and is_reply("HUL") and is_reply("2024-25") and is_reply("the standalone one")
    assert not is_reply("What was TCS' net profit in FY2025-26?") and not is_reply("TCS net profit 2025-26")


def test_question_without_a_company_uses_the_company_just_discussed(figure_store, ask):
    mem = Memory(":memory:")
    assert ask("What was the net profit?", mem=mem).status == "clarify"           # nothing discussed yet: must ask
    mem = Memory(":memory:")
    ask(Q_REV, mem=mem)
    a = ask("What was the net profit?", mem=mem)
    assert a.status == "answered" and a.companies == ["INFY"] and a.value == 180.0 and a.fiscal_years == ["2025-26"]
    assert any("taken from the previous question" in c for c in a.caveats)
    assert not any("previous question" in c for c in ask(Q_REV, mem=mem).caveats)   # everything stated: no note
    assert ask("What is the dress code?", mem=mem).status == "clarify"            # not understood: not attached to Infosys


# ---- added 17 Nov 2026: the model may not invent a year; summary topics are widened before searching ----
def test_a_year_the_user_never_gave_is_not_accepted_from_the_model(figure_store, ask):
    guess = model(plan={"intent": "fact", "companies": ["Infosys"], "fiscal_years": ["2025-26"], "item": "net_profit"})
    a = ask("What was Infosys' consolidated net profit?", guess)
    assert a.status == "clarify" and "fiscal year" in a.clarifying_question
    assert ask("What was Infosys' consolidated net profit in the latest year?", guess).fiscal_years == ["2025-26"]
    assert ask("What was Infosys' consolidated revenue from operations last year?").fiscal_years == ["2024-25"]


def test_summary_topic_is_widened_and_pages_are_not_repeated(monkeypatch, ask):
    import finsight.agent.executor as ex
    seen = {}

    def search(query, company=None, fiscal_year=None, top_k=5, **_):
        seen.update(query=query, top_k=top_k)
        pages = [86, 86, 86, 10, 41, 47, 11]                                      # the same page three times, then others
        return [{"page": p, "citation": f"HINDUNILVR-FY2526-p{p}", "score": 1.0, "text": f"[hdr]\nText of page {p}."} for p in pages]
    monkeypatch.setattr(ex, "search_report", search)
    good = {"answer": "Three points.", "key_points": [{"point": f"Point {p}", "citation": f"HINDUNILVR-FY2526-p{p}"} for p in (86, 10, 41)]}
    a = ask("Summarise the business performance of HUL in FY2025-26", model(summary=good))
    assert a.status == "answered"
    assert "revenue growth" in seen["query"] and "business performance" in seen["query"].lower()
    used = [t for t in a.trace if t.get("tool") == "search_report"][0]["result"]
    assert len(used) == 7                                                         # what the search returned ...
    bad = {"answer": "x", "key_points": [{"point": "p", "citation": "HINDUNILVR-FY2526-p11"}] * 3}
    assert ask("Summarise the business performance of HUL in FY2025-26", model(summary=bad)).status == "escalated"   # ... p11 was 5th page: not passed on
