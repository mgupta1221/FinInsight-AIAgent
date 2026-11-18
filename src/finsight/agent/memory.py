"""Conversation memory in SQLite (settings.memory_db).

NEW FILE (agent layer, 13 Nov 2026).

WHY: the SPEC requires follow-up questions to work ("and for FY2024-25?", "now compare with HDFC Bank").
The resolved slots of the last ANSWERED question are stored per session, so the planner can fill the gaps
of a short follow-up. Only verified answers are saved, so a failed question never pollutes the context.
A plain sqlite3 table is used (standard library); it is the same role LangGraph's SqliteSaver would play.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from finsight.config import REPO_ROOT, settings


def _default_path() -> Path:
    p = Path(settings.memory_db)
    return p if p.is_absolute() else REPO_ROOT / p


class Memory:
    def __init__(self, path: Path | str | None = None):
        path = path or _default_path()
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, slots TEXT, updated TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.db.execute("CREATE TABLE IF NOT EXISTS turns (id TEXT, question TEXT, status TEXT, answer TEXT, at TEXT DEFAULT CURRENT_TIMESTAMP)")

    def get(self, session_id: str) -> dict:
        row = self.db.execute("SELECT slots FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save(self, session_id: str, slots: dict) -> None:
        self.db.execute("INSERT INTO sessions (id, slots) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET slots = excluded.slots, "
                        "updated = CURRENT_TIMESTAMP", (session_id, json.dumps(slots)))
        self.db.commit()

    # NEW (17 Nov 2026): the question the agent could not finish because it had to ask something back.
    # WHY: slots were saved only after a successful answer. After a clarifying question ("Which part would you
    #      like?") nothing was kept, so the user's reply ("key risks") arrived as a brand-new question with no
    #      company, and the agent asked again, turn after turn. The unfinished question is now kept for exactly
    #      one turn under the key "_pending", beside the normal slots.
    def set_pending(self, session_id: str, question: str) -> None:
        slots = self.get(session_id)
        slots["_pending"] = question
        self.save(session_id, slots)

    def pop_pending(self, session_id: str) -> str | None:
        """Return the unfinished question, if any, and forget it (it is good for one reply only)."""
        slots = self.get(session_id)
        pending = slots.pop("_pending", None)
        if pending is not None:
            self.save(session_id, slots)
        return pending

    def log_turn(self, session_id: str, question: str, status: str, answer: str) -> None:
        self.db.execute("INSERT INTO turns (id, question, status, answer) VALUES (?, ?, ?, ?)", (session_id, question, status, answer))
        self.db.commit()

    def clear(self, session_id: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self.db.commit()
