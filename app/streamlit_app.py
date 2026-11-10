"""FinSight — Streamlit chat (Week 1).

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
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

import streamlit as st  # noqa: E402

from finsight.qa import answer_question  # noqa: E402
from finsight.tools.get_company_profile import _load as load_companies  # noqa: E402

st.set_page_config(page_title="FinSight", page_icon="📊", layout="wide")
st.title("📊 FinSight — Annual Report Q&A")
st.caption("Answers come from the actual reports, with the page they came from. Not investment advice.")

# --- Sidebar: optional company / year filters ---
index, _ = load_companies()
tickers = sorted({p["ticker"] for p in index.values()})
with st.sidebar:
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

for turn in st.session_state.history:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])

question = st.chat_input("Ask about a company's annual report…")
if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
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
    st.session_state.history.append({"role": "assistant", "content": result["answer"]})
