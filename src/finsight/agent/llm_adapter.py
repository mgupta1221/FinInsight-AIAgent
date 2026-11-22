"""A thin wrapper so the agent can run on the real endpoint or on a scripted fake.

NEW FILE (agent layer, 13 Nov 2026).

WHY: the agent's logic (slot checks, tool calls, critic, caps) must be testable without the network and
without spending tokens. Every node asks this adapter for a validated object; in production that is
finsight.llm.structured(), in unit tests it is FakeLLM returning scripted dictionaries. The adapter also
exposes `tokens`, the number of tokens the current question has used, for the per-question budget.
"""
from __future__ import annotations

from typing import Callable, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class RealLLM:
    """Uses finsight.llm (certificate, one request at a time, rate limit, retries, instructor validation)."""

    def __init__(self):
        from finsight import llm          # imported here so tests never need the openai / instructor stack
        self._llm = llm
        self._start = llm.TOKENS_USED

    @property
    def tokens(self) -> int:
        return self._llm.TOKENS_USED - self._start

    def json(self, system: str, user: str, schema: Type[T], max_tokens: int = 400) -> T:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        return self._llm.structured(messages, schema, max_tokens=max_tokens)


class FakeLLM:
    """For tests: `responder(schema_name, system, user)` returns a dict. No network; fixed token cost per call."""

    def __init__(self, responder: Callable[[str, str, str], dict], tokens_per_call: int = 300):
        self.responder, self.tokens, self.per_call, self.calls = responder, 0, tokens_per_call, []

    def json(self, system: str, user: str, schema: Type[T], max_tokens: int = 400) -> T:
        self.tokens += self.per_call
        self.calls.append(schema.__name__)
        return schema.model_validate(self.responder(schema.__name__, system, user))
