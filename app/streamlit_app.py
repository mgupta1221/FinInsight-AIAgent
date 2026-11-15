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
    st.header("Filters (optional)")
    company = st.selectbox("Company", ["(any)"] + tickers, index=0)
    fy = st.selectbox("Fiscal year", ["(any)", "2024-25", "2025-26"], index=0)
    top_k = st.slider("Passages to retrieve", 3, 10, 5)
    st.markdown("---")
    st.caption("Leave filters on **(any)** to let the search figure it out.")

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

for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])

question = st.chat_input("Ask about a company's annual report…")
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
                    agent_answer = run_agent(with_filters(question), session_id=st.session_state.session_id)
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
    st.session_state.history.append({"role": "assistant", "content": reply})
