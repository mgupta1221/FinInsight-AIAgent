"""Tests for the chat screen: the answer card helpers and (when Streamlit is installed) the screen itself.

NEW FILE (15 Nov 2026). The screen test drives app/streamlit_app.py without a browser, with a scripted model
and the made-up figure store from conftest.py: no network, no PDFs.
"""
import sys
from pathlib import Path

import pytest

from conftest import model
from finsight.agent.memory import Memory
from finsight.schemas import AgentAnswer, Figure, KeyPoint

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
from components import answer_markdown, input_rows  # noqa: E402


def test_answer_text_for_each_status():
    fig = Figure(name="revenue_from_operations", company="INFY", fiscal_year="2025-26", value=1000, unit="crore", page=287, citation="INFY-FY2526-p287")
    a = AgentAnswer(status="answered", answer="Revenue was ₹1,000.00 crore.", inputs=[fig], citations=["INFY-FY2526-p287"])
    assert "INFY-FY2526-p287" in answer_markdown(a)
    assert input_rows(a) == [{"Figure": "revenue_from_operations", "Company": "INFY", "Year": "FY2025-26", "Value": "1,000.00",
                              "Unit": "crore", "Read from": "FY2025-26 report, page 287", "Citation": "INFY-FY2526-p287"}]   # 19 Nov 2026: "Page" -> "Read from"
    prior = Figure(name="previous", company="INFY", fiscal_year="2024-25", value=900, unit="crore", page=287, citation="INFY-FY2526-p287")
    assert input_rows(AgentAnswer(status="answered", inputs=[prior]))[0]["Read from"] == "FY2025-26 report, page 287"   # NOT the FY2024-25 report
    s = AgentAnswer(status="answered", answer="Two risks.", key_points=[KeyPoint(point="Cyber risk", citation="ITC-FY2526-p110")])
    assert "- Cyber risk `[ITC-FY2526-p110]`" in answer_markdown(s)
    assert answer_markdown(AgentAnswer(status="clarify", clarifying_question="Which company do you mean?")) == "Which company do you mean?"
    assert answer_markdown(AgentAnswer(status="refused", answer="I can't give investment advice.")).startswith("I can't")


def test_chat_screen_uses_the_agent(figure_store, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import finsight.agent.graph as graph
    real_run, seen = graph.run, []

    def scripted_run(question, session_id="default", **_):
        seen.append(question)
        return real_run(question, session_id=session_id, llm=model(), memory=Memory(":memory:"))
    monkeypatch.setattr(graph, "run", scripted_run)

    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()
    assert not at.exception
    at.chat_input[0].set_value("What was Infosys' consolidated revenue from operations in FY2025-26?").run()
    assert not at.exception
    shown = " ".join(m.value for m in at.markdown)
    assert "1,000.00 crore" in shown and "INFY-FY2526-p287" in shown          # answer + citation on screen
    assert at.table and at.expander                                              # figures table + "How I got this"

    at.selectbox(key="filter_company").set_value("INFY").run()   # 19 Nov 2026: picked by key, the sidebar has more pickers now                                      # sidebar company filter
    at.chat_input[0].set_value("What was the net profit in FY2025-26?").run()
    assert seen[-1].endswith("for INFY") and not at.exception
    at.chat_input[0].set_value("Should I buy TCS shares?").run()
    assert at.warning and "investment advice" in at.warning[0].value
    # added 17 Nov 2026: touching a sidebar filter redraws the page; earlier answers must keep their full cards
    tables, expanders = len(at.table), len(at.expander)
    assert tables == 2 and expanders == 3                                        # two answers with figures, three traces
    at.selectbox(key="filter_fy").set_value("2024-25").run()   # 19 Nov 2026: picked by key, the sidebar has more pickers now
    assert not at.exception and (len(at.table), len(at.expander)) == (tables, expanders)
    assert at.warning and "investment advice" in at.warning[0].value            # the refusal is still shown as a refusal


# ---- added 19 Nov 2026: Quick lookup ----

def test_every_lookup_entry_is_understood_by_the_planner():
    """Each label in the pickers must lead the planner to the id beside it, for a company of the right kind."""
    import lookups
    from finsight.agent import planner
    from finsight.schemas import AgentPlan
    for is_bank, name in ((False, "Wipro"), (True, "HDFC Bank")):
        for label, ident, kind in lookups.figure_options(is_bank):
            q = lookups.build_question([name], label, ["2025-26"], "Consolidated")
            plan = planner.resolve(AgentPlan(intent="other"), q, {})
            assert ident in (plan.metric, plan.item), (q, plan.metric, plan.item)
            assert plan.fiscal_years == ["2025-26"] and len(plan.companies) == 1


def test_lookup_lists_follow_the_sector_and_build_the_three_kinds_of_question():
    import lookups
    from finsight.agent import planner
    from finsight.schemas import AgentPlan
    from finsight.tools.get_company_profile import _load
    profiles = list({p["ticker"]: p for p in _load()[0].values()}.values())
    assert lookups.sectors(profiles) == ["IT services", "FMCG", "Banks"]
    banks = lookups.companies_in(profiles, "Banks")
    assert len(banks) == 5 and all(p["is_bank"] for p in banks)
    bank_ids = {i for _, i, _ in lookups.figure_options(True)}
    other_ids = {i for _, i, _ in lookups.figure_options(False)}
    assert {"casa_ratio", "deposits", "advances"} <= bank_ids and not {"casa_ratio", "deposits"} & other_ids
    assert {"operating_margin", "revenue_from_operations"} <= other_ids and "operating_margin" not in bank_ids

    q = lookups.build_question(["HDFC Bank", "ICICI Bank", "Axis Bank"], "CASA ratio", ["2025-26"], "Standalone", "lowest")
    assert q == "Which of HDFC Bank, ICICI Bank and Axis Bank had the lowest standalone CASA ratio in FY2025-26?"
    plan = planner.resolve(AgentPlan(intent="other"), q, {})
    assert plan.intent == "compare_rank" and len(plan.companies) == 3 and plan.order == "lowest" and plan.metric == "casa_ratio"
    q = lookups.build_question(["Wipro"], "Net profit", ["2024-25", "2025-26"], "Consolidated")
    plan = planner.resolve(AgentPlan(intent="other"), q, {})
    assert plan.intent == "yoy" and plan.item == "net_profit" and plan.fiscal_years == ["2024-25", "2025-26"]


def test_quick_lookup_button_asks_the_agent(figure_store, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import finsight.agent.graph as graph
    real_run, seen = graph.run, []

    def scripted_run(question, session_id="default", **_):
        seen.append(question)
        return real_run(question, session_id=session_id, llm=model(), memory=Memory(":memory:"))
    monkeypatch.setattr(graph, "run", scripted_run)

    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()
    assert at.selectbox(key="lk_sector").value == "IT services"
    labels = [o[0] for o in at.selectbox(key="lk_figure_False").options] if not isinstance(at.selectbox(key="lk_figure_False").options[0], str) else at.selectbox(key="lk_figure_False").options
    assert any("Operating margin" in str(x) for x in labels) and not any("CASA" in str(x) for x in labels)
    at.selectbox(key="lk_sector").set_value("Banks").run()
    labels = [str(x) for x in at.selectbox(key="lk_figure_True").options]
    assert any("CASA" in x for x in labels) and not any("Operating margin" in x for x in labels)
    at.selectbox(key="lk_sector").set_value("IT services").run()
    at.multiselect(key="lk_companies_IT services").set_value(["Infosys"]).run()
    at.button(key="lk_go").click().run()
    assert not at.exception and seen and "Infosys" in seen[-1] and "FY2025-26" in seen[-1]
    assert any("Infosys" in m.value for m in at.markdown)                        # the built question is shown in the chat


def test_bank_ratios_stated_for_the_bank_itself_have_no_scope_choice():
    """Real run, 19 Nov 2026: "ICICI Bank's consolidated CASA ratio" could not be found; it exists standalone only."""
    import lookups
    from finsight.agent import planner
    from finsight.schemas import AgentPlan
    assert lookups.scope_is_fixed("casa_ratio", True) and not lookups.scope_is_fixed("deposits", True)
    assert not lookups.scope_is_fixed("return_on_assets", False)
    q = lookups.build_question(["ICICI Bank"], "CASA ratio", ["2025-26"], "")
    assert q == "What was ICICI Bank's CASA ratio in FY2025-26?"
    assert planner.resolve(AgentPlan(intent="other"), q, {}).scope == "standalone"
