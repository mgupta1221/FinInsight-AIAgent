# ORIGINAL PLACEHOLDER (kept):
# """Tool: create_note_draft. See BUILD_PLAN.md (Tools table) for purpose. TODO: implement with Pydantic args + ToolError."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
"""Tool: create_note_draft. Exports a verified answer as a Markdown analyst note.

This is the human-in-the-loop boundary of SPEC section 8: the note is a DRAFT with a "verify before use"
banner until a person approves it (approved=True, set by the UI's Approve button).
"""
from __future__ import annotations

import re
from datetime import datetime

from finsight.config import REPO_ROOT
from finsight.tools.base import ToolError, register

NOTES_DIR = REPO_ROOT / "results" / "notes"
BANNER = "> **DRAFT. AI-generated. Verify every figure against the cited page before use. Not investment advice.**"


@register("create_note_draft")
def create_note_draft(title: str, answer: dict, approved: bool = False) -> dict:
    """answer: an AgentAnswer as a dict. Returns {path, status, needs_approval}. Only verified answers export."""
    if not answer.get("verified"):
        raise ToolError("only verified answers can be exported")
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "note"
    path = NOTES_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{name}{'' if approved else '-DRAFT'}.md"
    lines = [f"# {title}", "", "" if approved else BANNER, "", answer.get("answer", ""), ""]
    if answer.get("formula"):
        lines += [f"**Formula:** `{answer['formula']}`", ""]
    if answer.get("inputs"):
        lines += ["| Input | Company | Year | Value | Unit | Source |", "| --- | --- | --- | --- | --- | --- |"]
        lines += [f"| {i['name']} | {i['company']} | FY{i['fiscal_year']} | {i['value']:,.2f} | {i['unit']} | {i.get('citation') or ''} |"
                  for i in answer["inputs"]]
        lines.append("")
    for k in answer.get("key_points", []):
        lines.append(f"- {k['point']} [{k['citation']}]")
    if answer.get("citations"):
        lines += ["", "**Sources:** " + ", ".join(answer["citations"]), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return {"path": str(path), "status": "final" if approved else "draft", "needs_approval": not approved}
