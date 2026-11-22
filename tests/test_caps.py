# ORIGINAL PLACEHOLDER (kept):
# """Tests: step cap, loop/duplicate-call blocking, and token-budget escalation. TODO (Week 2)."""
# import pytest
#
# @pytest.mark.skip(reason="agent loop not implemented yet")
# def test_step_cap_escalates():
#     ...
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
"""Tests: step cap, duplicate-call blocking, token-budget escalation, malformed model output."""
import pytest

from conftest import model
from finsight.agent.executor import Escalate, Run
from finsight.agent.llm_adapter import FakeLLM
from finsight.schemas import AgentPlan, AgentStep

PLAN = AgentPlan(intent="fact", companies=["INFY"], fiscal_years=["2025-26"], scope="consolidated", item="net_profit")


def test_step_cap_escalates():
    with pytest.raises(Escalate, match="limit is 10"):
        Run(PLAN, model(), []).execute([AgentStep(tool="value_for_company", args={"company": "INFY"})] * 11)


def test_repeated_identical_tool_call_is_blocked(figure_store):
    r = Run(PLAN, model(), [])
    r.statement_figure("INFY", "net_profit", "2025-26")
    r.statement_figure("INFY", "net_profit", "2025-26")
    assert sum(1 for t in r.trace if "repeat blocked" in t.get("note", "")) == 2      # the lookup and the unit conversion


def test_token_budget_escalates(figure_store, ask):
    a = ask("What was Infosys' consolidated revenue from operations in FY2025-26?", model(tokens_per_call=13_000))
    assert a.status == "escalated" and "token budget" in a.answer


def test_malformed_model_output_escalates(ask):
    def broken(schema, system, user):
        raise ValueError("not JSON")
    assert ask("What was Infosys' consolidated revenue from operations in FY2025-26?", FakeLLM(broken)).status == "escalated"
