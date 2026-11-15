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
                              "Unit": "crore", "Page": 287, "Citation": "INFY-FY2526-p287"}]
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

    at.selectbox[0].set_value("INFY").run()                                      # sidebar company filter
    at.chat_input[0].set_value("What was the net profit in FY2025-26?").run()
    assert seen[-1].endswith("for INFY") and not at.exception
    at.chat_input[0].set_value("Should I buy TCS shares?").run()
    assert at.warning and "investment advice" in at.warning[0].value
