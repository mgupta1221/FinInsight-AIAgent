"""The one place that talks to the LLM.

Wraps an OpenAI-compatible client pointed at the provided Qwen3-8B endpoint and enforces every
constraint from the Track B guide in a single place:

- HTTPS verification with the provided CA cert (settings.ca_cert_path).
- A global concurrency=1 lock + 60/min rate limiter (the endpoint allows one active request/key).
- Retry on 429/503/timeout with exponential backoff (2s, 4s, 8s) then raise.
- Hard-cap max_tokens <= settings.max_output_tokens (<=1024).
- Disable Qwen3 "thinking" and strip any <think>...</think> block before returning/validating.
- Structured output via instructor + Pydantic (retries with the validation error fed back).

Callers use `chat()` for plain text and `structured()` for a validated Pydantic object.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque

import httpx
import instructor
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from finsight.config import settings

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_RETRY_STATUS = {429, 500, 502, 503, 504}
_BACKOFFS = (2, 4, 8)  # seconds


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


class _RateLimiter:
    """Allow at most `per_min` calls in any rolling 60s window; also serialise to 1 at a time."""

    def __init__(self, per_min: int):
        self.per_min = per_min
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._times and now - self._times[0] >= 60:
                self._times.popleft()
            if len(self._times) >= self.per_min:
                sleep_for = 60 - (now - self._times[0])
                logger.info("rate limit: sleeping %.1fs", sleep_for)
                time.sleep(max(0.0, sleep_for))
            self._times.append(time.monotonic())


_rate = _RateLimiter(settings.rate_limit_per_min)
_concurrency = threading.Semaphore(settings.max_concurrency)


def _build_clients() -> tuple[OpenAI, "instructor.Instructor"]:
    http_client = httpx.Client(verify=settings.ca_cert_path, timeout=120.0)
    base = OpenAI(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key or "none",
        http_client=http_client,
    )
    return base, instructor.from_openai(base)


_raw_client: OpenAI | None = None
_structured_client = None


def _clients():
    global _raw_client, _structured_client
    if _raw_client is None:
        _raw_client, _structured_client = _build_clients()
    return _raw_client, _structured_client


def _extra_body() -> dict:
    # Qwen3: turn off the long reasoning so structured output fits the 1024-token cap.
    if settings.qwen_disable_thinking:
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}


def _with_retries(fn):
    last: Exception | None = None
    for attempt in range(len(_BACKOFFS) + 1):
        try:
            with _concurrency:
                _rate.acquire()
                return fn()
        except (APITimeoutError, APIConnectionError) as e:
            last = e
        except APIStatusError as e:
            if e.status_code not in _RETRY_STATUS:
                raise
            last = e
        if attempt < len(_BACKOFFS):
            delay = _BACKOFFS[attempt]
            logger.warning("LLM call failed (%s); retrying in %ss", last, delay)
            time.sleep(delay)
    raise RuntimeError(f"LLM call failed after retries: {last}") from last


def chat(messages: list[dict], max_tokens: int | None = None, temperature: float = 0.0) -> str:
    """Plain chat completion -> assistant text (with any <think> block stripped)."""
    raw, _ = _clients()
    cap = min(max_tokens or settings.max_output_tokens, settings.max_output_tokens)

    def _call():
        return raw.chat.completions.create(
            model=settings.model_name,
            messages=messages,
            max_tokens=cap,
            temperature=temperature,
            extra_body=_extra_body(),
        )

    resp = _with_retries(_call)
    return _strip_think(resp.choices[0].message.content or "")


def structured(messages: list[dict], schema, max_tokens: int | None = None, max_retries: int = 2):
    """Chat completion validated into `schema` (a Pydantic model); instructor retries on bad JSON."""
    _, sclient = _clients()
    cap = min(max_tokens or settings.max_output_tokens, settings.max_output_tokens)

    def _call():
        return sclient.chat.completions.create(
            model=settings.model_name,
            messages=messages,
            response_model=schema,
            max_tokens=cap,
            temperature=0.0,
            max_retries=max_retries,
            extra_body=_extra_body(),
        )

    return _with_retries(_call)
