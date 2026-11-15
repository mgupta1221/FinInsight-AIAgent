# ORIGINAL PLACEHOLDER (kept):
# """Tests: critic rejects untraceable numbers, missing citations, wrong formula/scope, advice. TODO (Week 2)."""
# import pytest
#
# @pytest.mark.skip(reason="critic not implemented yet")
# def test_rejects_uncited_figure():
#     ...
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
"""Tests for the critic rules."""
from finsight.agent.critic import review
from finsight.schemas import AgentAnswer, AgentPlan, Figure, KeyPoint

PLAN = AgentPlan(intent="fact", companies=["INFY"], fiscal_years=["2025-26"], scope="consolidated", item="revenue_from_operations")
FIG = Figure(name="revenue_from_operations", company="INFY", fiscal_year="2025-26", value=178650, unit="crore", page=287,
             citation="INFY-FY2526-p287")
RESULT = {"figures": [FIG], "values": {"INFY": {"value": 178650.0, "unit": "crore"}}}


def answer(text, **kw):
    return AgentAnswer(**{**dict(status="answered", answer=text, inputs=[FIG], citations=["INFY-FY2526-p287"]), **kw})


def test_accepts_grounded_answer_in_both_digit_groupings():
    assert review(answer("Revenue from operations was ₹178,650.00 crore in FY2025-26 (consolidated)."), PLAN, RESULT).ok
    assert review(answer("Revenue from operations was ₹1,78,650 crore in FY2025-26 (consolidated)."), PLAN, RESULT).ok


def test_rejects_untraceable_number():
    v = review(answer("Revenue was about ₹180,000 crore in FY2025-26 (consolidated)."), PLAN, RESULT)
    assert not v.ok and "not traceable" in v.reasons[0]


def test_rejects_uncited_figure():
    assert not review(answer("Revenue was ₹178,650 crore in FY2025-26.", citations=[]), PLAN, RESULT).ok
    no_page = FIG.model_copy(update={"page": None, "citation": None})
    assert not review(answer("Revenue was ₹178,650 crore in FY2025-26.", inputs=[no_page]), PLAN, RESULT).ok


def test_rejects_missing_year_wrong_scope_and_advice():
    assert not review(answer("Revenue was ₹178,650 crore (consolidated)."), PLAN, RESULT).ok
    assert not review(answer("Standalone revenue was ₹178,650 crore in FY2025-26."), PLAN, RESULT).ok
    assert not review(answer("Revenue was ₹178,650 crore in FY2025-26, so investors should buy."), PLAN, RESULT).ok


def test_rejects_wrong_formula():
    a = answer("Revenue was ₹178,650 crore in FY2025-26.", formula="net_profit / total_assets * 100")
    assert not review(a, PLAN, RESULT, expected_formula="net_profit / revenue_from_operations * 100").ok


def test_summary_must_cite_retrieved_pages():
    plan = AgentPlan(intent="summary", companies=["ITC"], fiscal_years=["2025-26"], topic="risks")
    result = {"passages": [{"citation": "ITC-FY2526-p110"}]}
    pts = [KeyPoint(point=f"risk {i}", citation="ITC-FY2526-p110") for i in range(3)]
    assert review(AgentAnswer(status="answered", answer="Three risks.", key_points=pts), plan, result).ok
    bad = [KeyPoint(point="risk", citation="ITC-FY2526-p999")] * 3
    assert not review(AgentAnswer(status="answered", answer="Three risks.", key_points=bad), plan, result).ok
