# ORIGINAL PLACEHOLDER (kept):
# """Reusable Streamlit widgets: answer card, citation links, 'How I got this' trace view. TODO (Week 3)."""
#
# IMPLEMENTED (15 Nov 2026) when the chat screen was connected to the agent.
"""Reusable Streamlit widgets: answer card and 'How I got this' trace view.

WHY a separate file: streamlit_app.py stays a short script (layout + chat loop), and the way an agent answer
is drawn lives in one place. `answer_markdown` has no Streamlit calls, so it is unit-tested without a browser.
"""
from __future__ import annotations

import json
import re

STATUS_LABEL = {
    "answered": "Answered",
    "clarify": "Need one more detail",
    "refused": "Out of scope",
    "escalated": "Could not answer reliably",
}


def answer_markdown(a) -> str:
    """The text shown in the chat bubble (and kept in the chat history) for an AgentAnswer."""
    if a.status == "clarify":
        return a.clarifying_question or a.answer or "Could you give me a little more detail?"
    text = a.answer or ""
    if a.status == "answered" and a.key_points:
        text += "\n\n" + "\n".join(f"- {k.point} `[{k.citation}]`" for k in a.key_points)
    if a.status == "answered" and a.citations and not a.key_points:
        text += "\n\nSource: " + ", ".join(f"`{c}`" for c in a.citations)
    return text


# CHANGED (19 Nov 2026): the table now says WHICH REPORT each page number belongs to.
# OLD:
# def input_rows(a) -> list[dict]:
#     """The figures an answer was built from, as table rows."""
#     return [{"Figure": f.name, "Company": f.company, "Year": f"FY{f.fiscal_year}",
#              "Value": f"{f.value:,.2f}" if f.value is not None else "", "Unit": f.unit or "",
#              "Page": f.page, "Citation": f.citation or ""} for f in a.inputs]
# WHY: in a year-on-year answer the previous year's figure is read from the previous-year column of the LATER
#      report, so both years are on the same basis. The row for FY2024-25 then showed "Page 354", which a
#      reader looks up in the FY2024-25 report and does not find: it is page 354 of the FY2025-26 report. The
#      report was only visible inside the citation code (HDFCBANK-FY2526-p354). The column "Page" is replaced
#      by "Read from", for example "FY2025-26 report, page 354".
def read_from(f) -> str:
    """ "FY2025-26 report, page 354" for a figure cited as HDFCBANK-FY2526-p354."""
    m = re.search(r"-FY(\d\d)(\d\d)-p", f.citation or "")
    report = f"FY20{m.group(1)}-{m.group(2)}" if m else f"FY{f.fiscal_year}"
    return f"{report} report, page {f.page}" if f.page else ""


def input_rows(a) -> list[dict]:
    """The figures an answer was built from, as table rows."""
    return [{"Figure": f.name, "Company": f.company, "Year": f"FY{f.fiscal_year}",
             "Value": f"{f.value:,.2f}" if f.value is not None else "", "Unit": f.unit or "",
             "Read from": read_from(f), "Citation": f.citation or ""} for f in a.inputs]


def render_agent_answer(st, a) -> None:
    """Draw one AgentAnswer: status, text, formula, input figures, caveats and the step-by-step trace."""
    if a.status == "answered":
        st.markdown(answer_markdown(a))
        # CHANGED (17 Nov 2026).  OLD: st.caption(("Checked: every number traces to a cited page." if a.verified else "Not verified.")
        # WHY: under a text summary that line overstated the check. For a summary the critic confirms only that
        #      each point cites a page that was actually retrieved; it cannot judge whether the points are the
        #      important ones.
        checked = ("Checked: each point cites a page that was retrieved. Read the pages to confirm the wording."
                   if a.key_points else "Checked: every number traces to a cited page.")
        st.caption((checked if a.verified else "Not verified.")
                   + f"  ·  {a.tokens_used:,} tokens")
    elif a.status == "clarify":
        st.info(answer_markdown(a))
    elif a.status == "refused":
        st.warning(answer_markdown(a))
    else:
        st.error(answer_markdown(a))
    if a.formula:
        st.markdown(f"**Formula:** `{a.formula}`")
    if a.inputs:
        st.markdown("**Figures used**")
        st.table(input_rows(a))
    for c in a.caveats:
        st.caption(f"Note: {c}")
    if a.trace:
        with st.expander(f"How I got this ({len(a.trace)} steps)"):
            for step in a.trace:
                st.code(json.dumps(step, ensure_ascii=False, default=str)[:1500], language="json")
