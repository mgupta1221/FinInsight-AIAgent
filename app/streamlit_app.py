"""FinSight — Streamlit chat.

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

from finsight.qa import answer_question  # noqa: E402
from finsight.tools.get_company_profile import _load as load_companies  # noqa: E402

# NEW (15 Nov 2026): the agent, its memory, and the answer card.
import uuid  # noqa: E402

from components import render_agent_answer, answer_markdown  # noqa: E402  (app/components.py)
import lookups  # noqa: E402  (app/lookups.py, 19 Nov 2026: the Quick lookup pickers)
from finsight.agent.graph import run as run_agent  # noqa: E402
from finsight.agent.memory import Memory  # noqa: E402
from finsight.corpus import years_in  # noqa: E402
from finsight.tools.company_match import find_companies  # noqa: E402

st.set_page_config(page_title="FinSight", page_icon="📊", layout="wide")
st.title("📊 FinSight — Annual Report Q&A")
st.caption("Answers come from the actual reports, with the page they came from. Not investment advice.")

# --- Sidebar: optional company / year filters ---
index, _ = load_companies()
tickers = sorted({p["ticker"] for p in index.values()})
with st.sidebar:
    # NEW (15 Nov 2026): choose the answer path; "New conversation" clears the agent's memory.
    mode = st.radio("Answer mode", ["Agent (recommended)", "Simple search (Week 1)"], index=0)
    if st.button("New conversation"):
        Memory().clear(st.session_state.get("session_id", ""))
        st.session_state.history = []
        st.session_state.session_id = uuid.uuid4().hex
    st.markdown("---")
    # NEW (19 Nov 2026): Quick lookup. Pick a sector, companies, a figure or ratio and a year; the button writes
    # the question and sends it to the agent exactly as if it had been typed (see app/lookups.py for why).
    # The figure list follows the sector: banks get deposits, advances, CASA ratio, gross NPA ...; the other
    # companies get revenue, net profit, operating margin ... One company = a lookup, two or more = a comparison.
    st.header("Quick lookup")
    profiles = list({p["ticker"]: p for p in index.values()}.values())
    lk_sector = st.selectbox("Sector", lookups.sectors(profiles), key="lk_sector")
    lk_pool = lookups.companies_in(profiles, lk_sector)
    lk_is_bank = any(p.get("is_bank") for p in lk_pool)
    lk_names = st.multiselect("Companies (two or more to compare)", [p["name"] for p in lk_pool],
                              default=[lk_pool[0]["name"]], key=f"lk_companies_{lk_sector}")
    lk_options = lookups.figure_options(lk_is_bank)
    lk_pick = st.selectbox("Figure or ratio", lk_options, key=f"lk_figure_{lk_is_bank}",
                           format_func=lambda o: f"{o[0]}  ({o[2]})")
    # the change between the two years is offered only where the agent can give it: one company, a reported figure
    lk_year_choices = ["2025-26", "2024-25"] + (["Change: 2024-25 to 2025-26"] if len(lk_names) == 1 and lk_pick[2] == "figure" else [])
    lk_year = st.selectbox("Fiscal year", lk_year_choices, key=f"lk_year_{len(lk_year_choices)}")
    # OLD: lk_scope = st.radio("Scope", ["Consolidated", "Standalone"], horizontal=True, key="lk_scope")
    # NEW (19 Nov 2026, later): no Scope picker for the ratios a bank reports for the bank itself (see lookups.py).
    if lookups.scope_is_fixed(lk_pick[1], lk_is_bank):
        lk_scope = ""
        st.caption("Scope: standalone. Banks state this ratio for the bank itself, not for the group.")
    else:
        # OLD: lk_scope = st.radio("Scope", ["Consolidated", "Standalone"], horizontal=True, key="lk_scope")
        # NEW (19 Nov 2026): for banks "Standalone" comes first, the same default the agent now uses for a bank.
        # OLD (earlier on 19 Nov):
        # lk_scope = st.radio("Scope", ["Standalone", "Consolidated"] if lk_is_bank else ["Consolidated", "Standalone"],
        #                     horizontal=True, key=f"lk_scope_{lk_is_bank}")
        # NEW (19 Nov 2026, later): the first choice is the default scope of the companies picked (planner.default_scope).
        from finsight.agent.planner import default_scope as _default_scope
        lk_first = _default_scope([p["ticker"] for p in lk_pool if p["name"] in lk_names]).capitalize()
        lk_scope = st.radio("Scope", [lk_first] + [x for x in ("Consolidated", "Standalone") if x != lk_first],
                            horizontal=True, key=f"lk_scope_{lk_first}")
    lk_order = st.radio("Rank by", ["highest", "lowest"], horizontal=True, key="lk_order") if len(lk_names) > 1 else "highest"
    lk_go = st.button("Get answer", type="primary", disabled=not lk_names, key="lk_go")
    st.markdown("---")
    st.header("Filters (optional)")
    # OLD: company = st.selectbox("Company", ["(any)"] + tickers, index=0)
    #      fy = st.selectbox("Fiscal year", ["(any)", "2024-25", "2025-26"], index=0)
    # NEW (19 Nov 2026): the same two pickers, now with a key, because the sidebar has other pickers too.
    company = st.selectbox("Company", ["(any)"] + tickers, index=0, key="filter_company")
    fy = st.selectbox("Fiscal year", ["(any)", "2024-25", "2025-26"], index=0, key="filter_fy")
    top_k = st.slider("Passages to retrieve", 3, 10, 5)
    st.markdown("---")
    st.caption("Leave filters on **(any)** to let the search figure it out.")
    # NEW (17 Nov 2026): say what the filters do in Agent mode, because changing one does not change old answers.
    st.caption("In Agent mode a filter is added only to a NEW question that names no company or year. "
               "Answers already on screen do not change.")

company_f = None if company == "(any)" else company
fy_f = None if fy == "(any)" else fy

# --- Chat history ---
if "history" not in st.session_state:
    st.session_state.history = []
# NEW (15 Nov 2026): one memory session per browser session, so follow-up questions ("And for FY2024-25?")
# reuse the company and metric of the previous question, and two users do not share a conversation.
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex
use_agent = mode.startswith("Agent")


def with_filters(q: str) -> str:
    """Add the sidebar company / year to the question, but only when the question itself names none."""
    if company_f and not find_companies(q):
        q += f" for {company_f}"
    if fy_f and not years_in(q):
        q += f" in FY{fy_f}"
    return q

# CHANGED (17 Nov 2026): earlier agent answers are redrawn as full cards, not as plain text.
# OLD:
# for turn in st.session_state.history:
#     with st.chat_message(turn["role"]):
#         st.markdown(turn["content"])
# WHY: Streamlit runs this whole script again on every click, including a change of a sidebar filter. The
#      earlier answers were then redrawn from their saved text only, so the formula, the figures table and
#      the "How I got this" steps disappeared as soon as a filter was touched. The answer object is now kept
#      with each turn (key "agent") and drawn the same way every time.
for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        if turn.get("agent") is not None:
            render_agent_answer(st, turn["agent"])
        else:
            st.markdown(turn["content"])

# OLD: question = st.chat_input("Ask about a company's annual report…")
# NEW (19 Nov 2026): a question can also come from the Quick lookup button. It is written out in full (company,
# figure, year), shown in the chat like a typed question, and answered the same way.
typed = st.chat_input("Ask about a company's annual report…")
from_lookup = None
if lk_go and lk_names:
    lk_years = ["2024-25", "2025-26"] if lk_year.startswith("Change") else [lk_year]
    from_lookup = lookups.build_question(lk_names, lk_pick[0], lk_years, lk_scope, lk_order)
question = typed or from_lookup
if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

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
            with st.spinner("Working on it…"):
                try:
                    # OLD: agent_answer = run_agent(with_filters(question), session_id=st.session_state.session_id)
                    # NEW (19 Nov 2026): a Quick lookup question is already complete, so the optional filters are not added to it.
                    agent_answer = run_agent(question if from_lookup and not typed else with_filters(question),
                                             session_id=st.session_state.session_id)
                except Exception as e:  # noqa: BLE001  (endpoint down, wrong key, missing figure store ...)
                    agent_answer = None
                    reply = f"⚠️ Error: {e}"
            if agent_answer is not None:
                render_agent_answer(st, agent_answer)
                reply = answer_markdown(agent_answer)
            else:
                st.error(reply)
        else:
            with st.spinner("Searching the reports…"):
                try:
                    result = answer_question(question, company=company_f, fiscal_year=fy_f, top_k=top_k)
                except Exception as e:  # noqa: BLE001
                    result = {"answer": f"⚠️ Error: {e}", "passages": [], "used_context": False}

            st.markdown(result["answer"])
            if result["passages"]:
                with st.expander(f"📄 Sources ({len(result['passages'])} passages)"):
                    for p in result["passages"]:
                        st.markdown(f"**`{p['citation']}`** — page {p['page']} · {p.get('section','')}")
                        st.caption(p["text"][:600] + ("…" if len(p["text"]) > 600 else ""))
            reply = result["answer"]
    # OLD: st.session_state.history.append({"role": "assistant", "content": reply})
    st.session_state.history.append({"role": "assistant", "content": reply,
                                     "agent": agent_answer if use_agent else None})     # see the note above the history loop
