"""Shared tool plumbing: ToolError and a simple registry so every tool behaves the same.

Each tool: typed Pydantic args in, structured result out, raises ToolError on failure
(the executor turns a ToolError into an observation fed back to the planner).
"""
from __future__ import annotations


class ToolError(Exception):
    """Raised by any tool when it cannot complete (bad args, missing data, etc.)."""


REGISTRY: dict[str, object] = {}


def register(name: str):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco
