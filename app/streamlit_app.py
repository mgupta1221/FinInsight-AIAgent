"""FinSight — Streamlit chat.

CHANGED (24 Nov 2026, mentor's review): the screen is a plain chat. The sidebar holds "New conversation" and the list
of past conversations; "Answer mode" (Basic search), "Quick lookup" and "Filters" are removed; an answer is exported
with one button, "Export to PDF". The notes below describe earlier states of this file and are kept as history.

CHANGED (15 Nov 2026): the chat now calls the AGENT (finsight.agent.graph.run) by default.
WHY: the Week-1 path below (retrieve passages -> let the model answer) cannot compute a ratio, compare
     companies, remember the previous question, refuse advice, or check its own numbers. The agent does all
     of these and returns the formula, the input figures with page citations and a step-by-step trace, which
     this screen now shows. The Week-1 path is NOT removed: choose "Simple search (Week 1)" in the sidebar.
     Old lines are kept as comments marked OLD. The original description of this file follows.

--- original description (Week 1) ---

Week 1: ask a plain question -> retrieve the right passages from the actual reports -> the model
answers USING ONLY those passages and cites the page. Optional company/year pickers narrow the
search. Retrieved passages (with page citations) are shown under each answer so every number is
checkable.

Weeks 2-3 extend this same screen with the full agent (formula + inputs + self-check), conversation
memory, the rich answer card, "How I got this" trace, and the DRAFT + Approve export.

Run:  streamlit run app/streamlit_app.py
(Requires: ingestion has been run, Qdrant is reachable, and OPENAI_API_KEY is set in .env.)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package + top-level modules importable when run via `streamlit run`.
ROOT = Path(__file__).resolve().parents[1]
# OLD: sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
# NEW (15 Nov 2026): the app folder too, so `from components import ...` works however the app is started.
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "app")]

import streamlit as st  # noqa: E402

# OLD (Basic search removed from the screen, 24 Nov 2026): from finsight.qa import answer_question  # noqa: E402
# OLD (only the removed sidebar pickers used it, 24 Nov 2026): from finsight.tools.get_company_profile import _load as load_companies  # noqa: E402

# NEW (15 Nov 2026): the agent, its memory, and the answer card.
import uuid  # noqa: E402

from components import render_agent_answer, answer_markdown  # noqa: E402  (app/components.py)
from components import scroll_to_latest, suggestion_buttons  # noqa: E402  (22 Nov 2026: follow-up suggestions, scrolling)
# OLD (replaced by Export to PDF, 24 Nov 2026): from components import note_controls  # noqa: E402
from components import conversation_list, pdf_button  # noqa: E402  (24 Nov 2026: list of past conversations, Export to PDF)
# OLD (Quick lookup removed from the screen, 24 Nov 2026; app/suggest.py still uses the module): import lookups  # noqa: E402
import history as chat_history  # noqa: E402  (app/history.py, 22 Nov 2026: past conversations)
from finsight.safety.pii import mask_pii  # noqa: E402  (22 Nov 2026: questions are stored masked)
from finsight.agent.graph import run as run_agent  # noqa: E402
from finsight.agent.memory import Memory  # noqa: E402
# OLD (only used by the removed filters, 24 Nov 2026): from finsight.corpus import years_in  # noqa: E402
# OLD (only used by the removed filters, 24 Nov 2026): from finsight.tools.company_match import find_companies  # noqa: E402

st.set_page_config(page_title="FinSight", page_icon="📊", layout="wide")
# NEW (24 Nov 2026, mentor's review): no "Deploy" button. It belongs to Streamlit's hosting service, not to FinSight.
# .streamlit/config.toml hides it (toolbarMode = "viewer"); this line does the same if the app is started from a
# folder without that file.
st.markdown("<style>.stAppDeployButton, [data-testid='stAppDeployButton'] { display: none !important; }</style>", unsafe_allow_html=True)
# NEW (24 Nov 2026, mentor's review): the name of the app at the top of the sidebar, beside the arrow that folds it.
# WHY: that corner was empty. Streamlit keeps it for a logo image; the project has none, so the name is written
#      there by a style rule. Nothing else on the screen moves.
st.markdown("""<style>
[data-testid="stSidebarHeader"]::before { content: "📊 FinSight"; font-size: 1.3rem; font-weight: 700; white-space: nowrap; }
</style>""", unsafe_allow_html=True)
st.title("📊 FinSight — Annual Report Q&A")
st.caption("Answers come from the actual reports, with the page they came from. Not investment advice.")

# --- Sidebar ---
# CHANGED (24 Nov 2026, mentor's review). The sidebar now holds two things: "New conversation" and the list of
# past conversations. Removed from the screen:
#   - "Answer mode" with "Basic search": the baseline is a tool of the evaluation (eval/run_eval.py --mode simple),
#     not something a user of the chat needs; the screen always uses the agent.
#   - "Quick lookup": the pickers are gone; a question is typed, and "Explore further" under an answer offers the
#     usual next questions. (app/lookups.py stays: app/suggest.py builds those questions with it.)
#   - "Filters": removed earlier the same day.
# Past conversations are a list with one line per conversation (components.conversation_list): a click opens it,
# the three dots beside it hold "Delete". The whole old sidebar follows as comments.
with st.sidebar:
    if st.button("New conversation", key="new_conversation", use_container_width=True):
        st.session_state.history = []
        st.session_state.session_id = uuid.uuid4().hex
    try:
        chat_store = chat_history.ChatStore()
        past = chat_store.chats(limit=100)
    except Exception:  # noqa: BLE001  the chat works without the list
        chat_store, past = None, []
    if past:
        clicked = conversation_list(st, past, st.session_state.get("session_id", ""))
        if clicked:
            what, chat_id = clicked
            if what == "open":
                st.session_state.history = chat_store.load(chat_id)
                st.session_state.session_id = chat_id            # follow-up questions continue this conversation
            else:
                chat_store.delete(chat_id)
                Memory().clear(chat_id)                          # what the agent remembered of it goes too
                if st.session_state.get("session_id") == chat_id:
                    st.session_state.history = []
                    st.session_state.session_id = uuid.uuid4().hex
            st.rerun()

# OLD SIDEBAR (until 24 Nov 2026), kept as comments:
# --- Sidebar: optional company / year filters ---
# index, _ = load_companies()
# tickers = sorted({p["ticker"] for p in index.values()})
# with st.sidebar:
    # NEW (15 Nov 2026): choose the answer path; "New conversation" clears the agent's memory.
    # OLD: mode = st.radio("Answer mode", ["Agent (recommended)", "Simple search (Week 1)"], index=0)
    # CHANGED (22 Nov 2026): the second choice is renamed. WHY: "Week 1" is the team's build schedule and means
    #      nothing to a user. The name now says what it is: one search and one model answer, with no plan, no
    #      calculation and no check. It is the baseline the evaluation compares the agent with; it is kept on the
    #      screen so the difference can be shown in a demo. The code below still tests mode.startswith("Agent").
#     mode = st.radio("Answer mode", ["Agent (recommended)", "Basic search (baseline, no checks)"], index=0,
#                     help="Agent: plans the question, reads the figures, calculates in code and checks every number against "
#                          "the page. Basic search: one search of the reports and one model answer, with no calculation "
#                          "and no check. It is the baseline the agent is compared with.")
#     if st.button("New conversation"):
        # OLD: Memory().clear(st.session_state.get("session_id", ""))
        # CHANGED (22 Nov 2026): the agent's memory of the conversation being left is no longer erased.
        # WHY: that conversation can now be opened again from "Past conversations" below, and a follow-up
        #      question there ("and for FY2024-25?") needs what the agent remembered. The new conversation gets
        #      a new id, so it starts with nothing remembered, exactly as before.
#         st.session_state.history = []
#         st.session_state.session_id = uuid.uuid4().hex

    # NEW (22 Nov 2026, mentor's review): past conversations. See app/history.py for what is stored and why.
    # If the database cannot be opened the chat still works; only this list is missing.
#     try:
#         chat_store = chat_history.ChatStore()
#         past = chat_store.chats()
#     except Exception:  # noqa: BLE001
#         chat_store, past = None, []
#     if past:
#         with st.expander(f"Past conversations ({len(past)})"):
#             by_id = {c["id"]: c for c in past}
#             picked = st.selectbox("Conversation", list(by_id), key="past_pick", label_visibility="collapsed",
#                                   format_func=lambda i: f"{by_id[i]['title']}  ·  {chat_history.when(by_id[i]['at'])}")
#             st.caption(f"{by_id[picked]['questions']} question(s). Opening it shows the answers as they were given; "
#                        "they are not asked again.")
#             col_open, col_delete = st.columns(2)
#             if col_open.button("Open", key="past_open"):
#                 st.session_state.history = chat_store.load(picked)
#                 st.session_state.session_id = picked            # follow-up questions continue this conversation
#             if col_delete.button("Delete", key="past_delete"):
#                 chat_store.delete(picked)
#                 Memory().clear(picked)                          # what the agent remembered of it goes too
#                 if st.session_state.get("session_id") == picked:
#                     st.session_state.history = []
#                     st.session_state.session_id = uuid.uuid4().hex
#                 st.rerun()
#     st.markdown("---")
    # NEW (19 Nov 2026): Quick lookup. Pick a sector, companies, a figure or ratio and a year; the button writes
    # the question and sends it to the agent exactly as if it had been typed (see app/lookups.py for why).
    # The figure list follows the sector: banks get deposits, advances, CASA ratio, gross NPA ...; the other
    # companies get revenue, net profit, operating margin ... One company = a lookup, two or more = a comparison.
#     st.header("Quick lookup")
#     profiles = list({p["ticker"]: p for p in index.values()}.values())
    # CHANGED (22 Nov 2026): the Quick lookup starts EMPTY. Nothing is chosen until the user chooses it.
    # OLD (the first sector, its first company, the first figure and FY2025-26 were pre-selected):
    #     lk_sector = st.selectbox("Sector", lookups.sectors(profiles), key="lk_sector")
    #     lk_names = st.multiselect("Companies (two or more to compare)", [p["name"] for p in lk_pool],
    #                               default=[lk_pool[0]["name"]], key=f"lk_companies_{lk_sector}")
    #     lk_pick = st.selectbox("Figure or ratio", lk_options, key=f"lk_figure_{lk_is_bank}", format_func=...)
    #     lk_year = st.selectbox("Fiscal year", lk_year_choices, key=f"lk_year_{len(lk_year_choices)}")
    # WHY: with defaults the panel always showed "IT services / Tata Consultancy Services / Operating margin /
    #      2025-26", which looked like a choice somebody had made, and "Get answer" could be pressed by mistake
    #      for values nobody picked. Now each picker shows "Choose ..." and "Get answer" is enabled only when a
    #      sector, at least one company, a figure and a year have been chosen. The company and figure lists
    #      still follow the sector, so they stay disabled until a sector is chosen.
#     lk_sector = st.selectbox("Sector", lookups.sectors(profiles), index=None, placeholder="Choose a sector", key="lk_sector")
#     lk_pool = lookups.companies_in(profiles, lk_sector) if lk_sector else []
#     lk_is_bank = any(p.get("is_bank") for p in lk_pool)
#     lk_names = st.multiselect("Companies (two or more to compare)", [p["name"] for p in lk_pool], default=[],
#                               placeholder="Choose one or more companies" if lk_sector else "Choose a sector first",
#                               disabled=not lk_sector, key=f"lk_companies_{lk_sector}")
#     lk_options = lookups.figure_options(lk_is_bank) if lk_sector else []
#     lk_pick = st.selectbox("Figure or ratio", lk_options, index=None, key=f"lk_figure_{lk_is_bank}" if lk_sector else "lk_figure_none",
#                            placeholder="Choose a figure or ratio" if lk_sector else "Choose a sector first",
#                            disabled=not lk_sector, format_func=lambda o: f"{o[0]}  ({o[2]})")
    # the change between the two years is offered only where the agent can give it: one company, a reported figure
#     lk_year_choices = ["2025-26", "2024-25"] + (["Change: 2024-25 to 2025-26"] if len(lk_names) == 1 and lk_pick and lk_pick[2] == "figure" else [])
#     lk_year = st.selectbox("Fiscal year", lk_year_choices, index=None, placeholder="Choose a year", key=f"lk_year_{len(lk_year_choices)}")
    # OLD: lk_scope = st.radio("Scope", ["Consolidated", "Standalone"], horizontal=True, key="lk_scope")
    # NEW (19 Nov 2026, later): no Scope picker for the ratios a bank reports for the bank itself (see lookups.py).
    # OLD: if lookups.scope_is_fixed(lk_pick[1], lk_is_bank):
    # CHANGED (22 Nov 2026): lk_pick is None until a figure is chosen; the Scope picker appears once companies are chosen.
#     if not (lk_pick and lk_names):
#         lk_scope = ""
#     elif lookups.scope_is_fixed(lk_pick[1], lk_is_bank):
#         lk_scope = ""
#         st.caption("Scope: standalone. Banks state this ratio for the bank itself, not for the group.")
#     else:
        # OLD: lk_scope = st.radio("Scope", ["Consolidated", "Standalone"], horizontal=True, key="lk_scope")
        # NEW (19 Nov 2026): for banks "Standalone" comes first, the same default the agent now uses for a bank.
        # OLD (earlier on 19 Nov):
        # lk_scope = st.radio("Scope", ["Standalone", "Consolidated"] if lk_is_bank else ["Consolidated", "Standalone"],
        #                     horizontal=True, key=f"lk_scope_{lk_is_bank}")
        # NEW (19 Nov 2026, later): the first choice is the default scope of the companies picked (planner.default_scope).
#         from finsight.agent.planner import default_scope as _default_scope
#         lk_first = _default_scope([p["ticker"] for p in lk_pool if p["name"] in lk_names]).capitalize()
#         lk_scope = st.radio("Scope", [lk_first] + [x for x in ("Consolidated", "Standalone") if x != lk_first],
#                             horizontal=True, key=f"lk_scope_{lk_first}")
#     lk_order = st.radio("Rank by", ["highest", "lowest"], horizontal=True, key="lk_order") if len(lk_names) > 1 else "highest"
    # OLD: lk_go = st.button("Get answer", type="primary", disabled=not lk_names, key="lk_go")
#     lk_ready = bool(lk_sector and lk_names and lk_pick and lk_year)      # 22 Nov 2026: everything must be chosen
#     lk_go = st.button("Get answer", type="primary", disabled=not lk_ready, key="lk_go")
    # REMOVED (24 Nov 2026, mentor's review): the "Filters (optional)" section (company, fiscal year, number of passages).
    # WHY: with the company filter on AXISBANK, the question "How did PWC perform FY24-25" was sent to the agent as
    #      "... for AXISBANK" and, after one clarifying question, answered with Axis Bank's net profit: an answer
    #      about a company the user had not asked about, taken from a sidebar setting that is easy to forget.
    #      Everything the filters offered exists in a safer form:
    #        - Quick lookup (above) builds a complete question from pickers;
    #        - a question that names no company gets "Which company do you mean?";
    #        - a follow-up reuses the company of the last answer and says so in a note under the answer.
    #      Basic search now runs exactly as in the evaluation (eval/run_eval.py --mode simple): no filter, 5 passages.
    # The old lines are kept below as comments.
#     st.markdown("---")
#     st.header("Filters (optional)")
#     # OLD: company = st.selectbox("Company", ["(any)"] + tickers, index=0)
#     #      fy = st.selectbox("Fiscal year", ["(any)", "2024-25", "2025-26"], index=0)
#     # NEW (19 Nov 2026): the same two pickers, now with a key, because the sidebar has other pickers too.
#     company = st.selectbox("Company", ["(any)"] + tickers, index=0, key="filter_company")
#     fy = st.selectbox("Fiscal year", ["(any)", "2024-25", "2025-26"], index=0, key="filter_fy")
#     top_k = st.slider("Passages to retrieve", 3, 10, 5)
#     st.markdown("---")
#     st.caption("Leave filters on **(any)** to let the search figure it out.")
#     # NEW (17 Nov 2026): say what the filters do in Agent mode, because changing one does not change old answers.
#     st.caption("In Agent mode a filter is added only to a NEW question that names no company or year. "
#                "Answers already on screen do not change.")
#
# company_f = None if company == "(any)" else company
# fy_f = None if fy == "(any)" else fy
# No filter is applied any more. The three names stay so that the commented lines further down can still be read.
# company_f, fy_f, top_k = None, None, 5

# --- Chat history ---
if "history" not in st.session_state:
    st.session_state.history = []
# NEW (15 Nov 2026): one memory session per browser session, so follow-up questions ("And for FY2024-25?")
# reuse the company and metric of the previous question, and two users do not share a conversation.
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex
# OLD: use_agent = mode.startswith("Agent")
use_agent = True                                     # 24 Nov 2026: the screen always uses the agent


# OLD (removed 24 Nov 2026 together with the Filters section; see the note in the sidebar code above):
# def with_filters(q: str) -> str:
#     """Add the sidebar company / year to the question, but only when the question itself names none."""
#     if company_f and not find_companies(q):
#         q += f" for {company_f}"
#     if fy_f and not years_in(q):
#         q += f" in FY{fy_f}"
#     return q

# CHANGED (17 Nov 2026): earlier agent answers are redrawn as full cards, not as plain text.
# OLD:
# for turn in st.session_state.history:
#     with st.chat_message(turn["role"]):
#         st.markdown(turn["content"])
# WHY: Streamlit runs this whole script again on every click, including a change of a sidebar filter. The
#      earlier answers were then redrawn from their saved text only, so the formula, the figures table and
#      the "How I got this" steps disappeared as soon as a filter was touched. The answer object is now kept
#      with each turn (key "agent") and drawn the same way every time.
# OLD: for turn in st.session_state.history:
# CHANGED (22 Nov 2026): the position of the turn is needed as a key for its Export / Approve buttons, and the
# question before it is the title of the note.
export_slot = None      # 24 Nov 2026 (later): where the Export to PDF button of the conversation is drawn
for turn_no, turn in enumerate(st.session_state.history):
    with st.chat_message(turn["role"]):
        if turn.get("agent") is not None:
            render_agent_answer(st, turn["agent"])
            # OLD: note_controls(st, turn["agent"], st.session_state.history[turn_no - 1]["content"] if turn_no else "Note",
            #                    f"{st.session_state.session_id}_{turn_no}")
            # OLD (24 Nov 2026): one button under every verified answer, each exporting its own answer:
            # pdf_button(st, turn["agent"], st.session_state.history[turn_no - 1]["content"] if turn_no else "Answer",
            #            f"{st.session_state.session_id}_{turn_no}")
            # NEW (24 Nov 2026, later): ONE button, under the newest reply, for the complete conversation.
            # It is drawn in a slot of its own so that it can be taken away when a new question is asked below;
            # the new reply then gets the button, with the new question and answer included.
            if turn_no == len(st.session_state.history) - 1:
                export_slot = st.empty()
                with export_slot.container():
                    pdf_button(st, st.session_state.history, f"{st.session_state.session_id}_{len(st.session_state.history)}")
            # NEW (22 Nov 2026): follow-up suggestions, under the newest answer only (older ones would clutter the page).
            if turn_no == len(st.session_state.history) - 1 and not st.session_state.get("suggested_question"):
                suggestion_buttons(st, turn["agent"], st.session_state.history[turn_no - 1]["content"] if turn_no else "",
                                   f"{st.session_state.session_id}_{turn_no}")
        else:
            st.markdown(turn["content"])

# OLD: question = st.chat_input("Ask about a company's annual report…")
# NEW (19 Nov 2026): a question can also come from the Quick lookup button. It is written out in full (company,
# figure, year), shown in the chat like a typed question, and answered the same way.
typed = st.chat_input("Ask about a company's annual report…")
from_lookup = None                                   # 24 Nov 2026: Quick lookup is removed; the name stays for the line below
# OLD: if lk_go and lk_names:
# OLD (until 24 Nov 2026):
# if lk_go and lk_ready:
#     lk_years = ["2024-25", "2025-26"] if lk_year.startswith("Change") else [lk_year]
#     from_lookup = lookups.build_question(lk_names, lk_pick[0], lk_years, lk_scope, lk_order)
# OLD: question = typed or from_lookup
# CHANGED (22 Nov 2026): a clicked follow-up suggestion is a third way to ask. Like a Quick lookup question it is
# already complete, so the optional sidebar filters are not added to it.
from_suggestion = st.session_state.pop("suggested_question", None)
question = typed or from_lookup or from_suggestion
if question:
    st.session_state.history.append({"role": "user", "content": question})
    if export_slot is not None:
        export_slot.empty()          # 24 Nov 2026 (later): the button moves under the reply to this question
    # NEW (22 Nov 2026): every turn is also stored for "Past conversations". A failure to store never stops the chat.
    def remember(role: str, content: str, agent=None) -> None:
        try:
            if chat_store is not None:
                chat_store.add(st.session_state.session_id, role, content, agent)
        except Exception:  # noqa: BLE001
            pass
    remember("user", mask_pii(question))
    with st.chat_message("user"):
        st.markdown(question)
    scroll_to_latest(st, len(st.session_state.history), back=1)      # 22 Nov 2026: show the question while the agent works

    # OLD (kept; this block ran for every question before 15 Nov 2026 and still runs in "Simple search" mode):
    #     with st.chat_message("assistant"):
    #         with st.spinner("Searching the reports…"):
    #             try:
    #                 result = answer_question(question, company=company_f, fiscal_year=fy_f, top_k=top_k)
    #             except Exception as e:  # noqa: BLE001
    #                 result = {"answer": f"⚠️ Error: {e}", "passages": [], "used_context": False}
    #         st.markdown(result["answer"])
    #         ... sources expander ...
    #     st.session_state.history.append({"role": "assistant", "content": result["answer"]})
    with st.chat_message("assistant"):
        if use_agent:
            # NEW (15 Nov 2026): the agent path.
            # OLD: with st.spinner("Working on it…"):
            #          try:
            #              agent_answer = run_agent(question if from_lookup and not typed else with_filters(question),
            #                                       session_id=st.session_state.session_id)
            #          except Exception as e: ...
            # CHANGED (22 Nov 2026): the stages are shown while the agent works.
            # WHY: a question that needs the model several times takes 10 to 30 seconds and the screen said only
            #      "Working on it...". The agent now reports each stage as it starts (on_stage in
            #      finsight.agent.graph.run); the box below shows them one under the other and closes when the
            #      answer is ready. It can be opened again to read the stages. The answer itself is unchanged.
            # OLD (earlier on 22 Nov 2026): a box (st.status) that listed every stage and stayed on the page, closed,
            #      with the label "Done. Stages the agent went through":
            #          with st.status("Working on it…", expanded=True) as progress:
            #              def show_stage(stage, message):
            #                  progress.update(label=f"{stage.capitalize()}: {message}…")
            #                  progress.write(f"**{stage.capitalize()}** · {message}")
            #              ... progress.update(label="Done. Stages the agent went through", state="complete", expanded=False)
            # CHANGED (22 Nov 2026, after trying it in the app): one line that shows only the stage running NOW and
            #      disappears when the answer is ready.
            # WHY: the closed box stayed above the answer, which was not wanted: the stages are of interest only
            #      while waiting. The full record of what the agent did is still under "How I got this".
            progress = st.empty()

            def show_stage(stage: str, message: str) -> None:
                progress.caption(f"⏳ **{stage.capitalize()}** · {message}…")
            show_stage("agent", "Starting")
            try:
                # NEW (19 Nov 2026): a Quick lookup question is already complete, so the optional filters are not added to it.
                # OLD: agent_answer = run_agent(question if from_lookup and not typed else with_filters(question), ...
                # OLD: agent_answer = run_agent(question if (from_lookup or from_suggestion) and not typed else with_filters(question), ...
                # CHANGED (24 Nov 2026): the question goes to the agent exactly as it was asked; nothing is added to it.
                agent_answer = run_agent(question, session_id=st.session_state.session_id, on_stage=show_stage)
            except Exception as e:  # noqa: BLE001  (endpoint down, wrong key, missing figure store ...)
                agent_answer = None
                reply = f"⚠️ Error: {e}"
            progress.empty()                                    # nothing of the stages is left on the page
            if agent_answer is not None:
                render_agent_answer(st, agent_answer)
                # NEW (22 Nov 2026): same controls and same key as in the history loop above, where this answer is
                # drawn from the next click on.
                # OLD: note_controls(st, agent_answer, question, f"{st.session_state.session_id}_{len(st.session_state.history)}")
                # OLD: pdf_button(st, agent_answer, question, f"{st.session_state.session_id}_{len(st.session_state.history)}")   # 24 Nov 2026
                # NEW (24 Nov 2026, later): the complete conversation, this answer included (it joins the history just below).
                pdf_button(st, st.session_state.history + [{"role": "assistant", "content": agent_answer.answer, "agent": agent_answer}],
                           f"{st.session_state.session_id}_{len(st.session_state.history) + 1}")
                suggestion_buttons(st, agent_answer, question, f"{st.session_state.session_id}_{len(st.session_state.history)}")   # 22 Nov 2026
                reply = answer_markdown(agent_answer)
            else:
                st.error(reply)
        # OLD (Basic search, removed from the screen on 24 Nov 2026; use_agent is always True):
#         else:
#             with st.spinner("Searching the reports…"):
#                 try:
                    # OLD: result = answer_question(question, company=company_f, fiscal_year=fy_f, top_k=top_k)
#                     result = answer_question(question, top_k=5)          # 24 Nov 2026: as in the evaluation of the baseline
#                 except Exception as e:  # noqa: BLE001
#                     result = {"answer": f"⚠️ Error: {e}", "passages": [], "used_context": False}

#             st.markdown(result["answer"])
#             if result["passages"]:
#                 with st.expander(f"📄 Sources ({len(result['passages'])} passages)"):
#                     for p in result["passages"]:
#                         st.markdown(f"**`{p['citation']}`** — page {p['page']} · {p.get('section','')}")
#                         st.caption(p["text"][:600] + ("…" if len(p["text"]) > 600 else ""))
#             reply = result["answer"]
    # OLD: st.session_state.history.append({"role": "assistant", "content": reply})
    st.session_state.history.append({"role": "assistant", "content": reply,
                                     "agent": agent_answer if use_agent else None})     # see the note above the history loop
    remember("assistant", reply, agent_answer if use_agent else None)                  # 22 Nov 2026: past conversations
    scroll_to_latest(st, len(st.session_state.history), back=2)      # 22 Nov 2026: the question at the top, its answer below
