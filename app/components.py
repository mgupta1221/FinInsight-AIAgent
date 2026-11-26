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


# NEW (26 Nov 2026): the table shown under "Citation" on the chat screen.
# WHY: asked for after trying the screen. The figures table had seven columns and two of them repeated what
#      the page link already says: "Year" (the link reads "FY2025-26 report, page 375") and the citation code
#      (HCLTECH-FY2526-p375). The unit had a column of its own. The table now has four columns:
#          Figure | Company | Value | Citation
#      - Value carries its unit: "16,652.00 crore".
#      - Citation is the page link that was called "Read from": "FY2025-26 report, page 375", which opens the
#        report at that page.
#      figures_table() and input_rows() above are unchanged: the exported PDF and the tests still use them.
def citation_table(a, link=None) -> str:
    """The figures of an answer as a Markdown table of four columns. `link(citation)` gives the page address, or None."""
    if link is None:
        try:
            import sources
            link = sources.page_link
        except Exception:  # noqa: BLE001
            link = lambda c: None  # noqa: E731
    rows = input_rows(a)
    if not rows:
        return ""
    out = ["| Figure | Company | Value | Citation |", "| --- | --- | ---: | --- |"]
    for row in rows:
        try:
            url = link(row["Citation"]) if row["Citation"] else None
        except Exception:  # noqa: BLE001  a problem with the sources file must never hide the figures
            url = None
        page = row["Read from"]
        if url and page:
            page = f"[{page}]({url})"
        value = f"{row['Value']} {row['Unit']}".strip()
        cells = [row["Figure"], row["Company"], value, page]
        out.append("| " + " | ".join(str(x).replace("|", "\\|") for x in cells) + " |")
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
    # OLD (until 26 Nov 2026): the table "Figures used" was always open, with seven columns:
    # if a.inputs:
    #     st.markdown("**Figures used**")
    #     # OLD: st.table(input_rows(a))
    #     st.markdown(figures_table(a))                           # 22 Nov 2026: a Markdown table, so "Read from" can be a link
    #     st.caption("Click an entry under \"Read from\" to open the report at that page of the PDF "
    #                "(the page of the file, not the number printed on it).")
    # NEW (26 Nov 2026): the figures are in a closed box named "Citation"; a click opens the table.
    # WHY: asked for after trying the screen: the answer should be short, with the sources one click away. The
    #      box stands where "How I got this" stood (see below), and the table has four columns (citation_table).
    if a.inputs:
        with st.expander("Citation"):
            st.markdown(citation_table(a))
            st.caption("Click an entry under \"Citation\" to open the report at that page of the PDF "
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
    # OLD (until 26 Nov 2026): the steps of the agent under the answer.
    # if a.trace:
    #     with st.expander(f"How I got this ({len(a.trace)} steps)"):
    #         for step in a.trace:
    #             st.code(json.dumps(step, ensure_ascii=False, default=str)[:1500], language="json")
    # REMOVED FROM THE SCREEN (26 Nov 2026). WHY: asked for after trying the screen; the list of steps is for the
    #      team, not for a reader of the answer. Nothing is lost: the answer still carries its trace (a.trace),
    #      the evaluation writes it to traces.jsonl, `python scripts/ask.py "<question>" --trace` prints it, and
    #      Langfuse shows it when tracing is on.


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


# NEW (22 Nov 2026): follow-up suggestions as buttons under the newest answer. The questions are made by code in
# app/suggest.py; see there for why and how. A click stores the question; the chat screen asks it on the next
# run exactly as if it had been typed.
def suggestion_buttons(st, a, question: str, key: str) -> None:
    try:
        import suggest
        items = suggest.suggestions(a, question)
    except Exception:  # noqa: BLE001  a problem here must never hide the answer
        items = []
    if not items:
        return
    # OLD (earlier on 22 Nov 2026): a grey caption and plain buttons.
    #     st.caption("You could also ask:")
    #     for col, (n, (text, full)) in zip(st.columns(len(items)), enumerate(items)):
    #         if col.button(text, key=f"suggest_{key}_{n}", help=full): ...
    # CHANGED (22 Nov 2026, after seeing it in the app): the heading is "Explore further" and the suggestions
    # stand in a lightly tinted box with tinted, rounded buttons, so they read as one separate area and not as
    # part of the answer. The colours are see-through tints of one green, so they work on a light and on a dark
    # page. The tint is tied to the keys of the box and the buttons (classes "st-key-..."), which Streamlit
    # writes from version 1.39 on; an older Streamlit shows the same box and buttons without the tint.
    st.markdown("""<style>
    [class*="st-key-explore_"] { background: rgba(46, 125, 107, 0.07); border-radius: 0.6rem; }
    [class*="st-key-suggest_"] button { background: rgba(46, 125, 107, 0.14); border: 1px solid rgba(46, 125, 107, 0.45);
                                         border-radius: 999px; font-weight: 600; }
    [class*="st-key-suggest_"] button:hover { background: rgba(46, 125, 107, 0.28); border-color: rgba(46, 125, 107, 0.9); }
    </style>""", unsafe_allow_html=True)
    try:
        box = st.container(border=True, key=f"explore_{key}")
    except TypeError:                                           # Streamlit before 1.39: a container takes no key
        box = st.container(border=True)
    with box:
        st.markdown("**Explore further**")
        # OLD (earlier on 22 Nov 2026): all buttons in one row.
        #     for col, (n, (text, full)) in zip(st.columns(len(items)), enumerate(items)):
        #         if col.button(text, key=f"suggest_{key}_{n}", help=full, use_container_width=True): ...
        # CHANGED (22 Nov 2026, after seeing it in the app): two buttons per row.
        # WHY: four buttons in one row were too narrow for their text; the screen showed "Same for FY202...",
        #      "Change from FY...", "Revenue from o...". With two per row each button has half the width and the
        #      whole text fits. The keys are unchanged.
        for start in range(0, len(items), 2):
            for col, n in zip(st.columns(2), range(start, min(start + 2, len(items)))):
                text, full = items[n]
                if col.button(text, key=f"suggest_{key}_{n}", help=full, use_container_width=True):
                    st.session_state["suggested_question"] = full
                    st.rerun()


# NEW (22 Nov 2026): bring the newest question to the top of the window.
# WHY: Streamlit redraws the page when a question is sent but keeps the scroll position. A user who had scrolled
#      up stayed there and had to scroll down by hand to see the answer. Streamlit has no setting for this, so a
#      few lines of browser script are placed on the page: they find the chat messages and scroll the one that
#      is `back` from the end into view (1 = the question just asked, while the agent works; 2 = the same
#      question once its answer is below it). It is only called when a new question is asked, so opening a past
#      conversation or changing a filter does not move the page. `n` makes each script different, otherwise the
#      browser would not run it a second time.
def scroll_to_latest(st, n: int, back: int = 1) -> None:
    try:
        import streamlit.components.v1 as html_component
        html_component.html(
            f"""<script>/* {n}-{back} */
            setTimeout(function () {{
              try {{
                const m = window.parent.document.querySelectorAll('[data-testid="stChatMessage"]');
                const t = m[m.length - {back}];
                if (t) t.scrollIntoView({{behavior: "smooth", block: "start"}});
              }} catch (e) {{}}
            }}, 150);
            </script>""", height=0)
    except Exception:  # noqa: BLE001  no scrolling is better than no answer
        pass


# NEW (24 Nov 2026, mentor's review): "Export to PDF" in place of "Export as note (DRAFT)" and "Approve".
# WHY: the review asked for one button that downloads the answer as a PDF at once. note_controls() above is kept
#      but no longer called by the chat screen. Two things of the earlier design stay: only an answer that passed
#      the agent's check gets the button (can_export), and the PDF itself carries the notice "check each figure
#      against the cited page ... not investment advice" (app/pdf_export.py).
#      The file is built when the answer is drawn, because a download button needs its content in advance; it is
#      kept for the session so that redrawing the page does not build it again.
# CHANGED (24 Nov 2026, later): the button exports the COMPLETE conversation, not one answer.
# WHY: asked for after trying it: "Export to PDF should export the complete conversation of that chat, not just
#      the latest question". There is now one button, under the newest reply, and its PDF holds every question
#      and reply of the open conversation (pdf_export.conversation_pdf). It is shown once the conversation has
#      at least one verified answer; a conversation of refusals only has nothing to export.
# OLD (one answer per button, a button under every verified answer):
# def pdf_button(st, a, question: str, key: str) -> None:
#     if not can_export(a):
#         return
#     try:
#         import pdf_export
#         cache = st.session_state.setdefault("pdf_cache", {})
#         if key not in cache:
#             cache[key] = pdf_export.answer_pdf(question, a)
#         data, name = cache[key], pdf_export.file_name(question)
#     except Exception:  # noqa: BLE001  no button is better than no answer
#         return
#     label, tip = "📄 Export to PDF", "Downloads this answer with its figures, pages and sources as a PDF file."
#     try:
#         st.download_button(label, data=data, file_name=name, mime="application/pdf", key=f"pdf_{key}", help=tip, on_click="ignore")
#     except TypeError:                                           # an older Streamlit: no on_click="ignore"
#         st.download_button(label, data=data, file_name=name, mime="application/pdf", key=f"pdf_{key}", help=tip)
def pdf_button(st, history: list[dict], key: str, slot=None) -> None:
    """`history`: the turns of the open conversation. `key`: unique for the conversation and its length."""
    if not any(can_export(t.get("agent")) for t in history if t.get("agent") is not None):
        return
    try:
        import pdf_export
        cache = st.session_state.setdefault("pdf_cache", {})
        if key not in cache:
            cache.clear()                                       # only the newest PDF is kept in memory
            cache[key] = pdf_export.conversation_pdf(history)
        first = next((t.get("content") for t in history if t.get("role") == "user"), "conversation")
        data, name = cache[key], pdf_export.file_name(first)
    except Exception:  # noqa: BLE001  no button is better than no answer
        return
    label, tip = "📄 Export to PDF", "Downloads the complete conversation, with figures, pages and sources, as a PDF file."
    try:
        st.download_button(label, data=data, file_name=name, mime="application/pdf", key=f"pdf_{key}", help=tip, on_click="ignore")
    except TypeError:                                           # an older Streamlit: no on_click="ignore"
        st.download_button(label, data=data, file_name=name, mime="application/pdf", key=f"pdf_{key}", help=tip)


# NEW (24 Nov 2026, mentor's review): past conversations as a list in the sidebar.
# WHY: they were in a drop-down list with an "Open" and a "Delete" button under it. The review asked for the
#      usual form of a chat application: every conversation is a line in the sidebar, a click on the line opens
#      it, and a small menu (three dots) beside it holds "Delete". With many conversations the list scrolls.
#      The function only draws the list and reports what was clicked; the chat screen does the opening and
#      deleting, as before. The conversation that is open is drawn with a frame.
# NEW (25 Nov 2026): the question shown before a conversation is deleted.
# WHY: asked for after trying the list: a click on the bin must not delete at once. A small window asks
#      "Do you want to delete this conversation?"; "Yes, delete" deletes it, "No" only closes the window.
#      The window is Streamlit's dialog. Which conversation is being asked about is kept in
#      st.session_state["confirm_delete"]; the answer "yes" is left in st.session_state["delete_confirmed"],
#      which conversation_list() below hands to the chat screen as ("delete", id). The deleting itself is
#      still done by the chat screen, as before.
def _confirm_delete(st, chat_id: str, title: str) -> None:
    def forget() -> None:                                       # the window was closed with its X
        st.session_state.pop("confirm_delete", None)
    try:
        window = st.dialog("Delete conversation", on_dismiss=forget)
    except TypeError:                                           # an older Streamlit: no on_dismiss
        window = st.dialog("Delete conversation")

    @window
    def ask() -> None:
        st.write("Do you want to delete this conversation?")
        st.caption(title)
        yes, no = st.columns(2)
        if yes.button("Yes, delete", key="confirm_delete_yes", type="primary", use_container_width=True):
            st.session_state.pop("confirm_delete", None)
            st.session_state["delete_confirmed"] = chat_id
            st.rerun()
        if no.button("No", key="confirm_delete_no", use_container_width=True):
            st.session_state.pop("confirm_delete", None)
            st.rerun()
    ask()


def conversation_list(st, past: list[dict], current: str):
    """Returns ("open", id), ("delete", id) or None."""
    import history as chat_history
    # NEW (25 Nov 2026): "Yes, delete" was pressed in the window above on the previous run.
    confirmed = st.session_state.pop("delete_confirmed", None)
    if confirmed:
        return ("delete", confirmed)
    # OLD (24 Nov 2026), commented: the titles stayed centred with these two rules.
    # st.markdown("""<style>
    # [class*="st-key-open_"] button { justify-content: flex-start; text-align: left; padding-left: 0.6rem; }
    # [class*="st-key-open_"] button p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    # </style>""", unsafe_allow_html=True)
    # NEW (25 Nov 2026): the titles of the past conversations start at the left.
    # WHY: Streamlit centres the text of a button in a box INSIDE the button, so a rule on the button alone did
    #      not move it. The rule now reaches the boxes inside the button as well and is marked important.
    st.markdown("""<style>
    [class*="st-key-open_"] button, [class*="st-key-open_"] button * { justify-content: flex-start !important; text-align: left !important; }
    [class*="st-key-open_"] button { padding-left: 0.6rem; }
    [class*="st-key-open_"] button > div, [class*="st-key-open_"] button [data-testid="stMarkdownContainer"] { width: 100%; min-width: 0; }
    [class*="st-key-open_"] button p { width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    </style>""", unsafe_allow_html=True)
    # NEW (24 Nov 2026, mentor's review): only the three dots on the menu button, no arrow beside them.
    # WHY: Streamlit draws a small down-arrow on every popover button and has no setting to switch it off, so
    #      the arrow (an svg picture inside the button) is hidden by a style rule, for the sidebar only. The
    #      three dots are text, so they stay.
    # OLD (24 Nov 2026, first try), commented:
    # st.markdown("""<style>
    # [data-testid="stSidebar"] [data-testid="stPopover"] button svg,
    # [data-testid="stSidebar"] [data-testid="stPopoverButton"] svg { display: none !important; }
    # [data-testid="stSidebar"] [data-testid="stPopover"] button { padding-left: 0.3rem; padding-right: 0.3rem; }
    # </style>""", unsafe_allow_html=True)
    # NEW (24 Nov 2026, later). WHY: the arrow was still there. In this Streamlit version the arrow is not an svg
    #      picture but an icon written with an icon font (stIconMaterial), so the rule above did not match it.
    #      Each menu now sits in a container with its own key ("menu_<id>"), which gives a class name the rule can
    #      rely on, and the rule hides the icon whichever way Streamlit draws it.
    # OLD (24 Nov 2026), commented: the style of the three-dot menu, which is replaced by a bin (see below).
    # st.markdown("""<style>
    # [class*="st-key-menu_"] button [data-testid="stIconMaterial"],
    # [class*="st-key-menu_"] button svg,
    # [class*="st-key-menu_"] button > div > :last-child:not(:first-child) { display: none !important; }
    # [class*="st-key-menu_"] button { padding-left: 0.3rem; padding-right: 0.3rem; }
    # </style>""", unsafe_allow_html=True)
    st.caption("Past conversations")
    box = st.container(height=440, border=False) if len(past) > 9 else st.container()
    clicked = None
    with box:
        for c in past:
            line, menu = st.columns([0.8, 0.2], vertical_alignment="center")
            n = c.get("questions", 0)
            tip = f"{c['title']}  \n{chat_history.when(c['at'])} · {n} question{'s' if n != 1 else ''}"
            if line.button(chat_history.label(c["title"], 28), key=f"open_{c['id']}", help=tip, use_container_width=True,
                           type="secondary" if c["id"] == current else "tertiary"):
                clicked = ("open", c["id"])
            # OLD (24 Nov 2026), commented: the popover straight in the column.
            # with menu.popover("⋮", use_container_width=True):
            #     if st.button("Delete", key=f"del_{c['id']}", use_container_width=True):
            #         clicked = ("delete", c["id"])
            # NEW: the same popover inside a container with a key, so the style rule above can find its button.
            # OLD (24 Nov 2026), commented: three dots that opened a small menu with "Delete".
            # with menu.container(key=f"menu_{c['id']}"):
            #     with st.popover("⋮", use_container_width=True):
            #         if st.button("Delete", key=f"del_{c['id']}", use_container_width=True):
            #             clicked = ("delete", c["id"])
            # NEW (25 Nov 2026): a bin in place of the three dots. A click asks first (see _confirm_delete above).
            if menu.button(":material/delete:", key=f"del_{c['id']}", help="Delete this conversation", type="tertiary"):
                st.session_state["confirm_delete"] = c["id"]
    asking = st.session_state.get("confirm_delete")
    if asking and not clicked:
        match = [c for c in past if c["id"] == asking]
        if match:
            _confirm_delete(st, asking, match[0]["title"])
        else:
            st.session_state.pop("confirm_delete", None)        # the conversation is no longer in the list
    elif clicked:
        st.session_state.pop("confirm_delete", None)            # another conversation was opened instead
    return clicked
