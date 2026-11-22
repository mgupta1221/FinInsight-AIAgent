"""Past conversations for the chat screen, kept in SQLite.

NEW FILE (22 Nov 2026, mentor's review: "maintaining the past chat history").

WHY: the chat on screen lived only in the browser tab (st.session_state). A refresh or a restart of the app
     lost it. The agent's own memory (finsight.agent.memory) keeps what it needs for follow-up questions, not
     the answers as shown. This file stores every turn of every conversation, with the full answer object, so
     the sidebar can list earlier conversations and open one again exactly as it was shown.

Where: the same database file as the agent's memory (settings.memory_db, store/memory.sqlite), in a table of its
own (chat_turns). The store/ folder is not committed to Git. Questions are stored with personal details masked
(the same mask_pii the agent uses for its log). The agent code is not changed by this file.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from finsight.config import REPO_ROOT, settings
from finsight.schemas import AgentAnswer


class ChatStore:
    def __init__(self, path: Path | str | None = None):
        if path is None:
            p = Path(settings.memory_db)
            path = p if p.is_absolute() else REPO_ROOT / p
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS chat_turns (n INTEGER PRIMARY KEY AUTOINCREMENT, chat TEXT, role TEXT, "
                        "content TEXT, agent TEXT, at TEXT)")

    def add(self, chat: str, role: str, content: str, agent: AgentAnswer | None = None) -> None:
        """Store one turn. `agent` is the full answer object of an agent reply (None for the user or simple search)."""
        self.db.execute("INSERT INTO chat_turns (chat, role, content, agent, at) VALUES (?, ?, ?, ?, ?)",
                        (chat, role, content, agent.model_dump_json() if agent is not None else None,
                         datetime.now().isoformat(timespec="seconds")))
        self.db.commit()

    def chats(self, limit: int = 30) -> list[dict]:
        """Stored conversations, the most recently used first: id, title (the first question), date, questions asked."""
        rows = self.db.execute(
            "SELECT chat, MIN(n), MAX(n), SUM(role = 'user') FROM chat_turns GROUP BY chat ORDER BY MAX(n) DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for chat, first, _last, asked in rows:
            content, at = self.db.execute("SELECT content, at FROM chat_turns WHERE n = ?", (first,)).fetchone()
            out.append({"id": chat, "title": label(content), "at": at, "questions": int(asked or 0)})
        return out

    def load(self, chat: str) -> list[dict]:
        """The turns of one conversation, in the form the chat screen keeps them: role, content, agent."""
        turns = []
        for role, content, agent in self.db.execute("SELECT role, content, agent FROM chat_turns WHERE chat = ? ORDER BY n", (chat,)):
            answer = None
            if agent:
                try:
                    answer = AgentAnswer.model_validate_json(agent)
                except ValueError:          # stored by an older version of the answer object: show the text only
                    answer = None
            turns.append({"role": role, "content": content, "agent": answer})
        return turns

    def delete(self, chat: str) -> None:
        self.db.execute("DELETE FROM chat_turns WHERE chat = ?", (chat,))
        self.db.commit()


def label(text: str, width: int = 48) -> str:
    """A one-line title for the list: the first question, shortened."""
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def when(at: str) -> str:
    """'2026-11-22T10:15:00' -> '22 Nov 10:15'."""
    try:
        return datetime.fromisoformat(at).strftime("%d %b %H:%M")
    except (TypeError, ValueError):
        return ""
