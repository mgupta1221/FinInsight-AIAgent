# ORIGINAL PLACEHOLDER (kept):
# """Guard node (code): first gate. Blocks injection, investment-advice/forecast requests, and
# out-of-corpus companies/years -> status=refused. TODO (Week 2)."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
"""Guard node (code): the first gate. Returns a refused answer, or None to let the question through.

Out-of-corpus YEARS are caught here (pattern match). Out-of-corpus COMPANIES are caught by the planner,
because recognising "Reliance Industries" as a company name needs the model's reading of the question.
"""
from __future__ import annotations

from finsight.safety.guard_rules import check
from finsight.schemas import AgentAnswer


def guard(question: str, trace: list[dict]) -> AgentAnswer | None:
    blocked = check(question)
    if not blocked:
        return None
    reason, text = blocked
    trace.append({"node": "guard", "refused": reason})
    return AgentAnswer(status="refused", refusal_reason=reason, answer=text)
