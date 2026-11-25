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


# NEW (22 Nov 2026, later): the figures table is now a Markdown table (so "Read from" can be a link), no longer
# st.table. The tests below counted `at.table`; they count the Markdown tables through this helper instead.
def lookups_options(is_bank: bool) -> list:
    import lookups
    return lookups.figure_options(is_bank)


def tables(at) -> list:
    return [m for m in at.markdown if m.value.startswith("| Figure |")]


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
    assert tables(at) and at.expander                                              # figures table + "How I got this"

    # OLD (until 24 Nov 2026): the sidebar filters were tested here. They are removed (mentor's review):
    # at.selectbox(key="filter_company").set_value("INFY").run()   # 19 Nov 2026: picked by key, the sidebar has more pickers now                                      # sidebar company filter
    # at.chat_input[0].set_value("What was the net profit in FY2025-26?").run()
    # assert seen[-1].endswith("for INFY") and not at.exception
    # at.chat_input[0].set_value("Should I buy TCS shares?").run()
    # assert at.warning and "investment advice" in at.warning[0].value
    # # added 17 Nov 2026: touching a sidebar filter redraws the page; earlier answers must keep their full cards
    # # OLD: n_tables, expanders = len(tables(at)), len(at.expander)
    # # CHANGED (22 Nov 2026): only the "How I got this" boxes are counted; the sidebar now also has a
    # # "Past conversations" box once a question has been stored.
    # traces = lambda: [e for e in at.expander if e.label.startswith("How I got this")]   # noqa: E731
    # n_tables, expanders = len(tables(at)), len(traces())
    # assert n_tables == 2 and expanders == 3                                        # two answers with figures, three traces
    # at.selectbox(key="filter_fy").set_value("2024-25").run()   # 19 Nov 2026: picked by key, the sidebar has more pickers now
    # assert not at.exception and (len(tables(at)), len(traces())) == (n_tables, expanders)
    # NEW (24 Nov 2026): no filter exists, and a question reaches the agent exactly as it was typed.
    assert not [w for w in at.selectbox if (w.key or "").startswith("filter_")] and not at.slider
    at.chat_input[0].set_value("What was the net profit in FY2025-26?").run()
    assert seen[-1] == "What was the net profit in FY2025-26?" and not at.exception          # nothing is added to it
    assert at.info and "Which company" in at.info[-1].value                                  # so the agent asks; it does not guess
    at.chat_input[0].set_value("Should I buy TCS shares?").run()
    assert at.warning and "investment advice" in at.warning[0].value
    # touching a sidebar picker redraws the page; earlier answers must keep their full cards
    traces = lambda: [e for e in at.expander if e.label.startswith("How I got this")]   # noqa: E731
    n_tables, expanders = len(tables(at)), len(traces())
    assert n_tables == 1 and expanders == 3                                        # one answer with figures, three traces
    # OLD: at.selectbox(key="lk_sector").set_value("Banks").run()      (Quick lookup is removed, later on 24 Nov 2026)
    assert not at.radio and not at.selectbox and not at.multiselect                # no answer mode, no pickers
    at.run()                                                                       # the page is drawn again
    assert not at.exception and (len(tables(at)), len(traces())) == (n_tables, expanders)
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


# OLD TEST (Quick lookup was removed from the screen on 24 Nov 2026; the lists in app/lookups.py are still tested above and below), kept as comments:
# def test_quick_lookup_button_asks_the_agent(figure_store, monkeypatch):
#     pytest.importorskip("streamlit")
#     from streamlit.testing.v1 import AppTest
#     import finsight.agent.graph as graph
#     real_run, seen = graph.run, []
#
#     def scripted_run(question, session_id="default", **_):
#         seen.append(question)
#         return real_run(question, session_id=session_id, llm=model(), memory=Memory(":memory:"))
#     monkeypatch.setattr(graph, "run", scripted_run)
#
#     at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()
#     # OLD: assert at.selectbox(key="lk_sector").value == "IT services"   (and the figure list was read straight away)
#     # CHANGED (22 Nov 2026): the Quick lookup starts empty; nothing can be asked until everything is chosen.
#     assert at.selectbox(key="lk_sector").value is None and at.selectbox(key="lk_figure_none").value is None
#     assert at.multiselect(key="lk_companies_None").value == [] and at.button(key="lk_go").disabled
#     at.selectbox(key="lk_sector").set_value("IT services").run()
#     assert at.multiselect(key="lk_companies_IT services").value == [] and at.button(key="lk_go").disabled
#     labels = at.selectbox(key="lk_figure_False").options
#     assert any("Operating margin" in str(x) for x in labels) and not any("CASA" in str(x) for x in labels)
#     at.selectbox(key="lk_sector").set_value("Banks").run()
#     labels = [str(x) for x in at.selectbox(key="lk_figure_True").options]
#     assert any("CASA" in x for x in labels) and not any("Operating margin" in x for x in labels)
#     at.selectbox(key="lk_sector").set_value("IT services").run()
#     at.multiselect(key="lk_companies_IT services").set_value(["Infosys"]).run()
#     assert at.button(key="lk_go").disabled and not seen                          # 22 Nov 2026: figure and year not chosen yet
#     figure = at.selectbox(key="lk_figure_False")
#     figure.set_value(next(o for o in lookups_options(False) if o[0] == "Revenue from operations")).run()
#     year = next(s for s in at.selectbox if str(s.key).startswith("lk_year_"))
#     assert year.value is None and at.button(key="lk_go").disabled
#     year.set_value("2025-26").run()
#     assert not at.button(key="lk_go").disabled
#     at.button(key="lk_go").click().run()
#     assert not at.exception and seen and "Infosys" in seen[-1] and "FY2025-26" in seen[-1]
#     assert any("Infosys" in m.value for m in at.markdown)                        # the built question is shown in the chat
#

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


# ---- added 22 Nov 2026: past conversations (mentor's review) ----
def test_past_conversations_are_stored_listed_opened_and_deleted():
    import history
    store = history.ChatStore(":memory:")
    answer = AgentAnswer(status="answered", intent="fact", answer="Revenue was 1,000.00 crore.", value=1000.0)
    store.add("c1", "user", "What was Infosys' consolidated revenue from operations in FY2025-26?")
    store.add("c1", "assistant", "Revenue was 1,000.00 crore.", answer)
    store.add("c2", "user", "Should I buy TCS shares?")
    store.add("c2", "assistant", "I cannot give investment advice.", AgentAnswer(status="refused", answer="I cannot give investment advice."))
    store.add("c1", "user", "and for FY2024-25?")                       # c1 is used again: it moves to the top
    listed = store.chats()
    assert [c["id"] for c in listed] == ["c1", "c2"] and listed[0]["questions"] == 2
    assert listed[0]["title"].startswith("What was Infosys") and len(listed[0]["title"]) <= 48
    turns = store.load("c1")
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[1]["agent"] == answer and turns[0]["agent"] is None      # the full answer object comes back
    store.delete("c1")
    assert [c["id"] for c in store.chats()] == ["c2"] and store.load("c1") == []
    assert history.when("2026-11-22T10:15:00") == "22 Nov 10:15" and history.when("") == ""


def test_chat_screen_keeps_a_conversation_and_opens_it_again(figure_store, monkeypatch, tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import finsight.agent.graph as graph
    from finsight.config import settings
    monkeypatch.setattr(settings, "memory_db", str(tmp_path / "memory.sqlite"))
    real_run = graph.run
    monkeypatch.setattr(graph, "run", lambda question, session_id="default", **_: real_run(question, session_id=session_id, llm=model(), memory=Memory(":memory:")))

    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()
    at.chat_input[0].set_value("What was Infosys' consolidated revenue from operations in FY2025-26?").run()
    assert not at.exception and len(tables(at)) == 1
    first = at.session_state.session_id
    next(b for b in at.button if b.label == "New conversation").click().run()
    assert not at.exception and len(tables(at)) == 0 and at.session_state.session_id != first

    # OLD (until 24 Nov 2026): a drop-down list with an "Open" and a "Delete" button:
    # again = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()      # the app is started again
    # assert not again.exception and len(tables(again)) == 0
    # assert again.selectbox(key="past_pick").options and "What was Infosys" in again.selectbox(key="past_pick").options[0]
    # again.button(key="past_open").click().run()
    # assert not again.exception and again.session_state.session_id == first
    # assert len(tables(again)) == 1 and "1,000.00 crore" in " ".join(m.value for m in again.markdown)   # the full card is back
    # again.button(key="past_delete").click().run()
    # assert not again.exception and len(tables(again)) == 0 and not [s for s in again.selectbox if s.key == "past_pick"]
    # NEW (24 Nov 2026): one line per conversation; a click on the line opens it, "Delete" is in the menu beside it
    again = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()      # the app is started again
    assert not again.exception and len(tables(again)) == 0 and not again.selectbox
    line = again.button(key=f"open_{first}")
    assert line.label.startswith("What was Infosys") and len(line.label) <= 28
    line.click().run()
    assert not again.exception and again.session_state.session_id == first
    assert len(tables(again)) == 1 and "1,000.00 crore" in " ".join(m.value for m in again.markdown)   # the full card is back
    # OLD (24 Nov 2026): again.button(key=f"del_{first}").click().run()      (deleted at once)
    # NEW (25 Nov 2026): the bin asks first. "No" keeps the conversation, "Yes, delete" removes it.
    again.button(key=f"del_{first}").click().run()
    assert not again.exception and again.button(key="confirm_delete_yes") and again.button(key="confirm_delete_no")
    again.button(key="confirm_delete_no").click().run()
    assert again.button(key=f"open_{first}") and not [b for b in again.button if (b.key or "").startswith("confirm_delete")]
    again.button(key=f"del_{first}").click().run()
    again.button(key="confirm_delete_yes").click().run()
    assert not again.exception and len(tables(again)) == 0
    assert not [b for b in again.button if (b.key or "").startswith(("open_", "del_"))]             # the list is empty again


# ---- added 22 Nov 2026: DRAFT note and Approve (SPEC section 8) ----
def test_only_a_verified_answer_can_become_a_note():
    from components import can_export
    assert can_export(AgentAnswer(status="answered", answer="x", verified=True))
    assert not can_export(AgentAnswer(status="answered", answer="x", verified=False))
    assert not can_export(AgentAnswer(status="escalated", answer="Unverified", verified=False))
    assert not can_export(AgentAnswer(status="refused", answer="x", verified=True))
    assert not can_export(AgentAnswer(status="clarify", clarifying_question="Which company?"))


# OLD TEST (the DRAFT and Approve buttons were replaced by Export to PDF on 24 Nov 2026), kept as comments:
# def test_note_is_a_draft_until_a_person_approves_it(figure_store, monkeypatch, tmp_path):
#     pytest.importorskip("streamlit")
#     from streamlit.testing.v1 import AppTest
#     import finsight.agent.graph as graph
#     import finsight.tools.create_note_draft as nd
#     from finsight.config import settings
#     monkeypatch.setattr(settings, "memory_db", str(tmp_path / "memory.sqlite"))
#     monkeypatch.setattr(nd, "NOTES_DIR", tmp_path / "notes")
#     real_run = graph.run
#     monkeypatch.setattr(graph, "run", lambda question, session_id="default", **_: real_run(question, session_id=session_id, llm=model(), memory=Memory(":memory:")))
#     files = lambda: sorted(p.name for p in (tmp_path / "notes").glob("*.md"))   # noqa: E731
#     button = lambda at, start: [b for b in at.button if (b.key or "").startswith(start)]   # noqa: E731
#
#     at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()
#     at.chat_input[0].set_value("Should I buy TCS shares?").run()
#     assert not at.exception and not button(at, "note_draft_")                    # a refusal has no Export button
#     at.chat_input[0].set_value("What was Infosys' consolidated revenue from operations in FY2025-26?").run()
#     assert not at.exception and len(button(at, "note_draft_")) == 1
#     button(at, "note_draft_")[0].click().run()
#     assert not at.exception and len(files()) == 1 and files()[0].endswith("-DRAFT.md")
#     draft = (tmp_path / "notes" / files()[0]).read_text(encoding="utf-8")
#     assert "DRAFT. AI-generated." in draft and "1,000.00" in draft and "INFY-FY2526-p287" in draft
#     approve = button(at, "note_approve_")[0]
#     assert approve.disabled                                                     # not before the reader confirms the check
#     next(c for c in at.checkbox if (c.key or "").startswith("note_checked_")).check().run()
#     button(at, "note_approve_")[0].click().run()
#     assert not at.exception and len(files()) == 2
#     final = next(f for f in files() if not f.endswith("-DRAFT.md"))
#     assert "DRAFT" not in (tmp_path / "notes" / final).read_text(encoding="utf-8")
#     assert any("Approved" in s.value for s in at.success) and not button(at, "note_approve_")
#

def test_stage_line_is_gone_once_the_answer_is_shown(figure_store, monkeypatch):
    """Added 22 Nov 2026: the stages are shown only while the agent works; nothing of them stays on the page."""
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import finsight.agent.graph as graph
    real_run, stages = graph.run, []

    def scripted_run(question, session_id="default", on_stage=None, **_):
        def note(stage, message):
            stages.append(stage)
            on_stage(stage, message)
        return real_run(question, session_id=session_id, llm=model(), memory=Memory(":memory:"), on_stage=note)
    monkeypatch.setattr(graph, "run", scripted_run)
    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()
    at.chat_input[0].set_value("What was Infosys' consolidated revenue from operations in FY2025-26?").run()
    assert not at.exception and {"guard", "planner", "executor", "writer", "critic"} <= set(stages)   # they were shown ...
    shown = " ".join(c.value for c in at.caption) + " ".join(m.value for m in at.markdown)
    assert "⏳" not in shown and "Stages the agent went through" not in shown and not at.get("status")  # ... and are gone


# ---- added 22 Nov 2026: links from a citation to the page of the report ----
def test_citation_becomes_a_link_to_the_page_of_the_report(tmp_path):
    import sources
    csv_file = tmp_path / "report_sources.csv"
    csv_file.write_text("filename,url,download_date,sha256\n"
                        "TCS-Annual-Report-2025-26.pdf,https://example.org/tcs-26.pdf,2026-11-10,x\n"
                        "HUL-Annual-Report-2024-25.pdf,https://example.org/hul-25.pdf#page=2,2026-11-10,x\n"
                        "Infosys-Annual-Report-2025-26.pdf,,,x\n", encoding="utf-8")
    assert sources.page_link("TCS-FY2526-p168", csv_file) == "https://example.org/tcs-26.pdf#page=168"
    assert sources.page_link("HINDUNILVR-FY2425-p44", csv_file) == "https://example.org/hul-25.pdf#page=44"   # typed "#page=2" is replaced
    assert sources.page_link("INFY-FY2526-p287", csv_file) is None            # no address in the file: no link
    assert sources.page_link("TCS-FY2425-p10", csv_file) is None              # that year's report is not in the file
    assert sources.page_link("not a citation", csv_file) is None and sources.page_link("XYZ-FY2526-p1", csv_file) is None
    a = AgentAnswer(status="answered", answer="x", verified=True, citations=["TCS-FY2526-p168"],
                    inputs=[Figure(name="ebit", company="TCS", fiscal_year="2025-26", value=1.0, unit="crore", page=168, citation="TCS-FY2526-p168"),
                            Figure(name="revenue", company="INFY", fiscal_year="2025-26", value=1.0, unit="crore", page=287, citation="INFY-FY2526-p287")])
    assert sources.links_markdown(a, csv_file) == "**Open the cited page:** [TCS-FY2526-p168](https://example.org/tcs-26.pdf#page=168)"
    assert sources.links_markdown(AgentAnswer(status="clarify", clarifying_question="Which company?"), csv_file) == ""


def test_every_report_in_the_sources_file_can_be_linked():
    """Each of the 15 companies and both years resolves to a row of data/report_sources.csv (when it has an address)."""
    import csv
    import sources
    from finsight.tools.get_company_profile import _load
    rows = list(csv.DictReader(open(sources.CSV_PATH, encoding="utf-8-sig", newline="")))
    with_url = {r["filename"] for r in rows if (r.get("url") or "").startswith("http")}
    index, _ = _load()
    for prof in {p["ticker"]: p for p in index.values()}.values():
        for fy in ("2024-25", "2025-26"):
            name = f"{prof['pdf_prefix']}-Annual-Report-{fy}.pdf"
            link = sources.page_link(f"{prof['ticker']}-FY{fy[2:4]}{fy[5:]}-p7")
            assert (link is not None) == (name in with_url), name
            assert link is None or link.endswith("#page=7")


def test_read_from_is_the_link_to_the_page_one_link_per_row():
    """Added 22 Nov 2026 (later): figures from several pages each carry their own link, inside the table."""
    from components import figures_table
    a = AgentAnswer(status="answered", answer="x", verified=True, inputs=[
        Figure(name="net_profit", company="HDFCBANK", fiscal_year="2025-26", value=2.0, unit="crore", page=354, citation="HDFCBANK-FY2526-p354"),
        Figure(name="net_profit", company="HDFCBANK", fiscal_year="2024-25", value=1.0, unit="crore", page=355, citation="HDFCBANK-FY2526-p355"),
        Figure(name="net_profit", company="SBIN", fiscal_year="2025-26", value=3.0, unit="crore", page=12, citation="SBIN-FY2526-p12")])
    link = lambda c: None if c.startswith("SBIN") else f"https://example.org/r.pdf#page={c.rsplit('-p', 1)[1]}"   # noqa: E731
    lines = figures_table(a, link).splitlines()
    assert lines[0] == "| Figure | Company | Year | Value | Unit | Read from | Citation |" and len(lines) == 5
    assert "[FY2025-26 report, page 354](https://example.org/r.pdf#page=354)" in lines[2]
    assert "[FY2025-26 report, page 355](https://example.org/r.pdf#page=355)" in lines[3]      # the other page, its own link
    assert "| FY2025-26 report, page 12 |" in lines[4]                                         # no address: plain text
    assert figures_table(AgentAnswer(status="clarify", clarifying_question="Which company?"), link) == ""


def test_each_key_point_and_each_source_is_its_own_link():
    """Added 22 Nov 2026: a summary cites several pages; each citation opens its own page."""
    from components import linked_answer, figures_table
    link = lambda c: f"https://example.org/{c.split('-p')[0]}.pdf#page={c.split('-p')[1]}" if not c.startswith("INFY") else None  # noqa: E731
    s = AgentAnswer(status="answered", answer="Two risks.", verified=True,
                    key_points=[KeyPoint(point="Cyber risk is managed by a layered framework", citation="ITC-FY2526-p110"),
                                KeyPoint(point="Commodity prices are volatile", citation="ITC-FY2526-p11")])
    text = linked_answer(s, link)
    assert "[ITC-FY2526-p110](https://example.org/ITC-FY2526.pdf#page=110)" in text
    assert "[ITC-FY2526-p11](https://example.org/ITC-FY2526.pdf#page=11)" in text and "`" not in text
    c = AgentAnswer(status="answered", answer="TCS is higher.", citations=["TCS-FY2526-p168", "INFY-FY2526-p287"])
    text = linked_answer(c, link)
    assert "[TCS-FY2526-p168](https://example.org/TCS-FY2526.pdf#page=168)" in text and "`INFY-FY2526-p287`" in text   # no address: stays plain
    two = AgentAnswer(status="answered", answer="x", inputs=[
        Figure(name="net_profit", company="TCS", fiscal_year="2025-26", value=2.0, unit="crore", page=168, citation="TCS-FY2526-p168"),
        Figure(name="net_profit", company="TCS", fiscal_year="2024-25", value=1.0, unit="crore", page=170, citation="TCS-FY2526-p170")])
    table = figures_table(two, link)
    assert "[FY2025-26 report, page 168](https://example.org/TCS-FY2526.pdf#page=168)" in table      # each row opens its own page
    assert "[FY2025-26 report, page 170](https://example.org/TCS-FY2526.pdf#page=170)" in table


# ---- added 22 Nov 2026: follow-up suggestions and scrolling ----
def test_follow_up_suggestions_are_built_by_code_from_the_answer():
    import suggest
    fig = Figure(name="net_profit", company="INFY", fiscal_year="2025-26", value=180.0, unit="crore", page=287, citation="INFY-FY2526-p287")
    fact = AgentAnswer(status="answered", intent="fact", verified=True, companies=["INFY"], fiscal_years=["2025-26"], scope="consolidated", inputs=[fig])
    got = suggest.suggestions(fact)
    assert got[0] == ("Same for FY2024-25", "What was Infosys's consolidated net profit in FY2024-25?")
    assert got[1] == ("Change from FY2024-25 to FY2025-26", "How did Infosys's consolidated net profit change from FY2024-25 to FY2025-26?")
    assert ("Revenue from operations", "What was Infosys's consolidated revenue from operations in FY2025-26?") in got
    assert all(text != "Net profit" for text, _ in got) and 2 <= len(got) <= 4       # the figure just answered is not offered again
    ratio = AgentAnswer(status="answered", intent="ratio", metric="operating_margin", companies=["TCS"], fiscal_years=["2024-25"], scope="consolidated")
    texts = [t for t, _ in suggest.suggestions(ratio)]
    assert texts[0] == "Same for FY2025-26" and not any(t.startswith("Change") for t in texts)   # no "change" for a ratio
    bank = AgentAnswer(status="answered", intent="ratio", metric="casa_ratio", companies=["HDFCBANK"], fiscal_years=["2025-26"], scope="standalone")
    got = suggest.suggestions(bank)
    assert got[0][1] == "What was HDFC Bank's CASA ratio in FY2024-25?"               # no scope word: banks state it standalone only
    assert {"Net profit", "Deposits"} <= {t for t, _ in got} and "Operating margin" not in {t for t, _ in got}
    summ = AgentAnswer(status="answered", intent="summary", companies=["ITC"], fiscal_years=["2025-26"])
    got = suggest.suggestions(summ, "Summarise the top risks ITC lists in its FY2025-26 report.")
    assert [t for t, _ in got] == ["Business performance", "Strategy and outlook", "Management commentary"]
    assert got[0][1] == "Summarise the business performance of ITC in FY2025-26."
    for none in (AgentAnswer(status="refused", answer="no"), AgentAnswer(status="clarify", clarifying_question="Which company?"),
                 AgentAnswer(status="answered", intent="compare", companies=["TCS", "INFY"], fiscal_years=["2025-26"])):
        assert suggest.suggestions(none) == []


def test_every_suggested_question_is_understood_by_the_planner(figure_store, fake_search, ask):
    """A suggestion must never lead to a refusal or to "which company?": it is a complete question."""
    import suggest
    fig = Figure(name="net_profit", company="INFY", fiscal_year="2025-26", value=180.0, unit="crore", page=287, citation="INFY-FY2526-p287")
    fact = AgentAnswer(status="answered", intent="fact", verified=True, companies=["INFY"], fiscal_years=["2025-26"], scope="consolidated", inputs=[fig])
    for _, q in suggest.suggestions(fact):
        a = ask(q)
        assert a.status in ("answered", "escalated") and a.companies == ["INFY"], (q, a.status, a.answer)   # escalated = figure not in the small test store
    good = {"answer": "ITC points.", "key_points": [{"point": p, "citation": "ITC-FY2526-p110"} for p in
            ("The company grew revenue in every segment during the year under review", "Margins held despite higher input costs across categories",
             "Capital spending continued on new capacity for the foods business")]}
    summ = AgentAnswer(status="answered", intent="summary", companies=["ITC"], fiscal_years=["2025-26"])
    for _, q in suggest.suggestions(summ, "Summarise the top risks ITC lists in its FY2025-26 report."):
        a = ask(q, model(summary=good))
        assert a.status == "answered" and a.intent == "summary" and a.companies == ["ITC"], (q, a.status, a.answer)


def test_a_clicked_suggestion_is_asked_like_a_typed_question(figure_store, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import finsight.agent.graph as graph
    real_run, seen = graph.run, []

    def scripted_run(question, session_id="default", **_):
        seen.append(question)
        return real_run(question, session_id=session_id, llm=model(), memory=Memory(":memory:"))
    monkeypatch.setattr(graph, "run", scripted_run)
    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()
    at.chat_input[0].set_value("What was Infosys' consolidated net profit in FY2025-26?").run()
    assert not at.exception
    buttons = [b for b in at.button if (b.key or "").startswith("suggest_")]
    assert buttons and buttons[0].label == "Same for FY2024-25"
    assert any(m.value == "**Explore further**" for m in at.markdown)              # 22 Nov 2026: the heading of the suggestions box
    buttons[0].click().run()
    assert not at.exception and seen[-1] == "What was Infosys's consolidated net profit in FY2024-25?"
    assert len(seen) == 2 and any(m.value == seen[-1] for m in at.markdown)        # asked once, and shown as the user's question
    newest = [b for b in at.button if (b.key or "").startswith("suggest_")]
    assert all(b.key != buttons[0].key for b in newest)                            # the earlier answer no longer carries suggestions


# ---- added 24 Nov 2026: the mentor's review ----
def test_a_company_outside_the_corpus_is_refused_by_code_whatever_the_model_says(figure_store, ask):
    """Mentor's session: "How did PWC perfom FY24-25" got "Which figure or ratio would you like?" and then Axis Bank's
    net profit, because a sidebar filter had added "for AXISBANK". The filter is gone; the name is refused in code."""
    from finsight.agent.planner import unknown_company
    for q, name in (("How did PWC perfom FY24-25", "PWC"), ("WHat did PWC perform fY25-26", "PWC"), ("how did pwc perform in fy24-25", "PwC"),
                    ("RIL revenue in FY2025-26", "RIL"), ("What about L&T?", "L&T"), ("net profit of reliance in FY2025-26", "Reliance"),
                    ("Tata Motors revenue FY2025-26", "Tata Motors"), ("What was Reliance Industries' revenue in FY2025-26?", "Reliance Industries")):
        assert unknown_company(q) == name, q
        a = ask(q)
        assert a.status == "refused" and a.refusal_reason == "not_in_corpus" and a.answer.startswith(f"{name} is not in my corpus"), (q, a.answer)
    # later on 24 Nov 2026: the years are named only when the question names a year
    assert ask("What is the Net profit of PCJ").answer == "PCJ is not in my corpus. I cover 15 companies."
    assert ask("What is the netprofit of PCJ for FY25-26").answer == "PCJ is not in my corpus. I cover 15 companies for FY2024-25 and FY2025-26."
    assert ask("What about L&T?").answer == "L&T is not in my corpus. I cover 15 companies."
    for q in ("What was the EPS?", "What is the ROE in FY2025-26?", "and the MD&A?", "Casa Rato", "WHAT WAS THE PROFIT", "What was the profit?",
              "Which Bank had the highest CASA ratio in FY2025-26?", "Kotak Mahindra Bank net profit", "tech mahindra revenue",
              "What was Tata Consultancy Services's consolidated operating margin in FY2025-26?", "Compare the two companies.", "GDP growth in FY2025-26"):
        assert unknown_company(q) is None, q


# ---- added later on 24 Nov 2026: the plain chat screen of the mentor's review ----
def test_the_sidebar_holds_new_conversation_and_past_conversations_only(figure_store, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import finsight.agent.graph as graph
    real_run = graph.run
    monkeypatch.setattr(graph, "run", lambda question, session_id="default", **_: real_run(question, session_id=session_id, llm=model(), memory=Memory(":memory:")))
    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()
    assert not at.exception and [b.label for b in at.sidebar.button] == ["New conversation"]
    assert not at.radio and not at.selectbox and not at.multiselect and not at.slider       # no Answer mode, Quick lookup or Filters
    assert not any("Quick lookup" in h.value or "Filters" in h.value for h in at.sidebar.header)
    at.chat_input[0].set_value("What was Infosys' consolidated revenue from operations in FY2025-26?").run()
    at.chat_input[0].set_value("What was Infosys' consolidated net profit in FY2025-26?").run()
    keys = [b.key for b in at.sidebar.button]
    current = at.session_state.session_id
    assert keys == ["new_conversation", f"open_{current}", f"del_{current}"]                # one line for the conversation, with its menu
    assert any(c.value == "Past conversations" for c in at.sidebar.caption)


def test_export_to_pdf_is_one_button_and_only_for_a_verified_answer(figure_store, monkeypatch):
    pytest.importorskip("streamlit")
    pymupdf = pytest.importorskip("pymupdf")
    from streamlit.testing.v1 import AppTest
    import finsight.agent.graph as graph
    real_run = graph.run
    monkeypatch.setattr(graph, "run", lambda question, session_id="default", **_: real_run(question, session_id=session_id, llm=model(), memory=Memory(":memory:")))
    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=30).run()
    at.chat_input[0].set_value("Should I buy TCS shares?").run()
    assert not at.exception and not at.get("download_button")                       # a refusal cannot be exported
    at.chat_input[0].set_value("What was Infosys' consolidated revenue from operations in FY2025-26?").run()
    exports = at.get("download_button")
    assert not at.exception and len(exports) == 1 and exports[0].proto.label.endswith("Export to PDF")
    assert not [b for b in at.button if (b.key or "").startswith("note_")] and not at.checkbox      # no DRAFT, no Approve
    data = next(iter(at.session_state["pdf_cache"].values()))
    assert data[:5] == b"%PDF-"
    text = " ".join(" ".join(page.get_text() for page in pymupdf.open(stream=data, filetype="pdf")).split())
    assert "1,000.00" in text and "INFY-FY2526-p287" in text and "Not investment advice" in text and "DRAFT" not in text
    # 24 Nov 2026 (later): the PDF is the complete conversation: the refused question is in it too, marked as refused
    assert "FinSight conversation" in text and "1. Should I buy TCS shares?" in text and "Refused:" in text
    assert "2. What was Infosys' consolidated revenue from operations in FY2025-26?" in text
    at.chat_input[0].set_value("What was Infosys' consolidated net profit in FY2025-26?").run()
    exports = at.get("download_button")
    assert not at.exception and len(exports) == 1                                   # still one button, under the newest reply
    data = next(iter(at.session_state["pdf_cache"].values()))
    text = " ".join(" ".join(page.get_text() for page in pymupdf.open(stream=data, filetype="pdf")).split())
    text = text.replace("\ufb01", "fi")                                            # the PDF font joins f and i into one sign
    assert "3. What was Infosys' consolidated net profit in FY2025-26?" in text and "1,000.00" in text and "180.00" in text


def test_the_pdf_of_an_answer_has_its_figures_key_points_and_the_notice():
    pymupdf = pytest.importorskip("pymupdf")
    import pdf_export
    fig = Figure(name="net_profit", company="INFY", fiscal_year="2025-26", value=29474.0, unit="crore", page=287, citation="INFY-FY2526-p287")
    a = AgentAnswer(status="answered", verified=True, answer="Infosys's net profit was \u20b929,474.00 crore in FY2025-26 (consolidated).",
                    inputs=[fig], citations=["INFY-FY2526-p287"], caveats=["Amounts are in crore."], formula="net_profit / revenue_from_operations * 100")
    body = pdf_export.answer_html("What was Infosys' net profit?", a, [{"Figure": "net_profit", "Value": "29,474.00", "Citation": "INFY-FY2526-p287"}])
    assert "Rs 29,474.00 crore" in body and "\u20b9" not in body and "<table>" in body and "Not investment advice." in body
    assert "&lt;b&gt;" in pdf_export.answer_html("<b>bold?</b>", a, [])                      # text of a question is never read as HTML
    text = " ".join(" ".join(p.get_text() for p in pymupdf.open(stream=pdf_export.answer_pdf("What was Infosys' net profit?", a), filetype="pdf")).split())
    assert "29,474.00" in text and "FY2025-26 report, page 287" in text and "Formula" in text and "Note: Amounts are in crore." in text
    s = AgentAnswer(status="answered", verified=True, answer="Two risks.", key_points=[KeyPoint(point="Cyber risk is managed by a layered framework. " * 400, citation="ITC-FY2526-p110"),
                                                                                         KeyPoint(point="Commodity prices are volatile.", citation="ITC-FY2526-p112")])
    doc = pymupdf.open(stream=pdf_export.answer_pdf("Summarise the top risks ITC lists in its FY2025-26 report.", s), filetype="pdf")
    text = " ".join(" ".join(p.get_text() for p in doc).split())
    assert doc.page_count >= 2 and "ITC-FY2526-p112" in text and "Key points" in text       # a long answer runs over to a second page
    assert pdf_export.file_name("What was Infosys' net profit in FY2025-26?") == "FinSight_what-was-infosys-net-profit-in-fy2025-26.pdf"
    assert pdf_export.file_name("???") == "FinSight_answer.pdf"



def test_the_sidebar_shows_the_name_and_the_menu_button_has_no_arrow():
    """24 Nov 2026 (mentor's review): the name FinSight at the top of the sidebar; three dots only on the menu."""
    here = Path(__file__).resolve().parents[1] / "app"
    page, parts = (here / "streamlit_app.py").read_text(encoding="utf-8"), (here / "components.py").read_text(encoding="utf-8")
    assert 'stSidebarHeader"]::before { content: "📊 FinSight"' in page
    # OLD (24 Nov 2026): assert '[class*="st-key-menu_"] button [data-testid="stIconMaterial"]' in parts and "display: none" in parts
    # NEW (25 Nov 2026): a bin in place of the three dots, a question before deleting, titles at the left.
    assert 'menu.button(":material/delete:"' in parts and "Do you want to delete this conversation?" in parts
    assert 'button * { justify-content: flex-start !important; text-align: left !important; }' in parts
