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


# NEW (22 Nov 2026, later): the figures table with the page link INSIDE the "Read from" column.
# WHY: the links were on one line under the table ("Open the cited page: ..."). With figures from several pages
#      (a comparison, a year-on-year change) the reader had to match each link to its row. Now every row carries
#      its own link: "FY2025-26 report, page 168" opens that report at page 168. st.table cannot hold a link in
#      every Streamlit version, so the table is written as a Markdown table, which can. input_rows() above is
#      unchanged and still gives the plain rows (used by the tests and the exported note).
def figures_table(a, link=None) -> str:
    """The figures of an answer as a Markdown table. `link(citation)` gives the address of the page, or None."""
    if link is None:
        try:
            import sources
            link = sources.page_link
        except Exception:  # noqa: BLE001
            link = lambda c: None  # noqa: E731
    rows = input_rows(a)
    if not rows:
        return ""
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---:" if c == "Value" else "---" for c in cols) + " |"]
    for row in rows:
        cells = dict(row)
        try:
            url = link(row["Citation"]) if row["Citation"] else None
        except Exception:  # noqa: BLE001  a problem with the sources file must never hide the figures
            url = None
        if url and cells["Read from"]:
            cells["Read from"] = f"[{cells['Read from']}]({url})"
        out.append("| " + " | ".join(str(cells[c]).replace("|", "\\|") for c in cols) + " |")
    return "\n".join(out)


# NEW (22 Nov 2026, later): the answer text with every citation turned into a link to its page.
# WHY: a summary cites a different page for each key point, and a comparison cites several pages on its "Source"
#      line. One line of links under the answer made the reader match link to point. Now the citation at the end
#      of each key point, and each citation on the "Source" line, is itself the link. answer_markdown() above is
#      unchanged: it is still the plain text kept in the chat history and used for the exported note.
def linked_answer(a, link=None) -> str:
    """answer_markdown(a) with `[CITATION]` and `CITATION` replaced by links, where the report has an address."""
    text = answer_markdown(a)
    if link is None:
        try:
            import sources
            link = sources.page_link
        except Exception:  # noqa: BLE001
            return text
    cites = list(a.citations or []) + [k.citation for k in a.key_points or []]
    for c in sorted({c for c in cites if c}, key=len, reverse=True):          # longest first: p11 must not eat p110
        try:
            url = link(c)
        except Exception:  # noqa: BLE001
            url = None
        if url:
            text = text.replace(f"`[{c}]`", f"[{c}]({url})").replace(f"`{c}`", f"[{c}]({url})")
    return text


def render_agent_answer(st, a) -> None:
    """Draw one AgentAnswer: status, text, formula, input figures, caveats and the step-by-step trace."""
    if a.status == "answered":
        # OLD: st.markdown(answer_markdown(a))
        st.markdown(linked_answer(a))                           # 22 Nov 2026: citations in the text are links
        if a.key_points:
            st.caption("Click the citation after a key point to open the report at that page of the PDF "
                       "(the page of the file, not the number printed on it).")
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
        # OLD: st.table(input_rows(a))
        st.markdown(figures_table(a))                           # 22 Nov 2026: a Markdown table, so "Read from" can be a link
        st.caption("Click an entry under \"Read from\" to open the report at that page of the PDF "
                   "(the page of the file, not the number printed on it).")
    # NEW (22 Nov 2026): links that open the report on the company's website at the cited page.
    # WHY: the reader had to find the report and the page by hand to check a figure. The addresses are in
    #      data/report_sources.csv (see app/sources.py). Shown for every answer that cites a page; a report
    #      without an address simply gets no link.
    try:
        import sources
        links = sources.links_markdown(a)
    except Exception:  # noqa: BLE001  a problem with the file must never hide the answer
        links = ""
    # OLD: if links:
    # CHANGED (22 Nov 2026, later): with a figures table the links are in its "Read from" column, so this line is
    #      shown only for answers without a table (summaries, and refusals that cite a page).
    # CHANGED AGAIN (22 Nov 2026): an answered question has its links in the text (linked_answer) and in the table,
    #      so the separate line is left only for other answers that cite a page (a refusal that points to a page).
    if links and not a.inputs and a.status != "answered":
        st.markdown(links)
        st.caption("Opens the report at that page of the PDF (the page of the file, not the number printed on it).")
    for c in a.caveats:
        st.caption(f"Note: {c}")
    if a.trace:
        with st.expander(f"How I got this ({len(a.trace)} steps)"):
            for step in a.trace:
                st.code(json.dumps(step, ensure_ascii=False, default=str)[:1500], language="json")


# NEW (22 Nov 2026): DRAFT note and Approve (SPEC section 8, the human-in-the-loop boundary).
# WHY: the SPEC says an exported note is a DRAFT with a "verify before use" banner until a person clicks Approve.
#      The tool that writes the note (finsight.tools.create_note_draft) has existed since 13 Nov 2026, but the
#      screen had no button for it. A chat answer stays beside its sources; a note leaves the app, so a person
#      must sign it off first. Three rules are enforced here:
#        1. only an answered and verified answer gets the button (no note from "Unverified", refused or clarify);
#        2. the first click writes a DRAFT (file name ends in -DRAFT, banner at the top);
#        3. Approve is enabled only after the reader ticks that the figures were checked; it writes the final
#           note without the banner and offers it for download.
def can_export(a) -> bool:
    """True if this answer may become a note: answered and passed the check."""
    return getattr(a, "status", None) == "answered" and bool(getattr(a, "verified", False))


def note_controls(st, a, title: str, key: str) -> None:
    """The Export / Approve controls under one answer. `key` is unique for the answer (conversation id + position)."""
    if not can_export(a):
        return
    from pathlib import Path

    import finsight.tools.create_note_draft as note_tool
    notes = st.session_state.setdefault("notes", {})
    note = notes.get(key)
    if note is None:
        if not st.button("📝 Export as note (DRAFT)", key=f"note_draft_{key}"):
            return
        out = note_tool.create_note_draft(title, a.model_dump(), approved=False)
        note = notes[key] = {"draft": out["path"], "final": None}
    if note["final"] is None:
        with st.expander("DRAFT note. Not final until approved.", expanded=True):
            st.caption(f"Saved as {Path(note['draft']).name} in results/notes/")
            st.markdown(Path(note["draft"]).read_text(encoding="utf-8"))
            checked = st.checkbox("I have checked the figures against the cited pages.", key=f"note_checked_{key}")
            if st.button("Approve", key=f"note_approve_{key}", type="primary", disabled=not checked):
                out = note_tool.create_note_draft(title, a.model_dump(), approved=True)
                note["final"] = out["path"]
                st.rerun()
    else:
        final = Path(note["final"])
        st.success(f"Approved. Final note saved as {final.name} in results/notes/")
        st.download_button("Download the final note", data=final.read_text(encoding="utf-8"), file_name=final.name,
                           mime="text/markdown", key=f"note_download_{key}")
