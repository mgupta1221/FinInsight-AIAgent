"""Simple Langfuse tracing helpers."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

from finsight.config import settings

logger = logging.getLogger(__name__)

_langfuse = None
_langfuse_init = False
_lock = threading.Lock()


def get_langfuse():
    """Return the shared Langfuse client, or ``None`` if tracing is disabled."""
    global _langfuse, _langfuse_init
    if _langfuse_init:
        return _langfuse
    with _lock:
        if _langfuse_init:
            return _langfuse
        if settings.langfuse_enabled:
            try:
                from langfuse import Langfuse
                _langfuse = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
                logger.info("Langfuse tracing enabled (%s)", settings.langfuse_host)
            except Exception:  # noqa: BLE001
                logger.warning("Langfuse import/init failed; tracing disabled", exc_info=True)
                _langfuse = None
        _langfuse_init = True
    return _langfuse


# --- Thread-local observation stack ---
_local = threading.local()


def _stack() -> list:
    if not hasattr(_local, "obs"):
        _local.obs = []
    return _local.obs


def current_observation():
    """Return the innermost active Langfuse observation (span/trace), or ``None``."""
    s = _stack()
    return s[-1] if s else None


@contextmanager
def observation_context(obs):
    """Push *obs* as the current observation for the duration of the block."""
    s = _stack()
    s.append(obs)
    try:
        yield obs
    finally:
        s.pop()


def flush() -> None:
    """Flush any buffered events to Langfuse."""
    lf = get_langfuse()
    if lf:
        try:
            lf.flush()
        except Exception:  # noqa: BLE001
            pass
