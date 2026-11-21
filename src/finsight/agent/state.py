# ORIGINAL PLACEHOLDER (kept):
# """Shared LangGraph state passed between agents (the 'memory sheet').
#
# Holds the question, resolved slots (companies/years/statement/metric), tool observations,
# the draft answer, the critic verdict, retry counts, and the final status.
# TODO (Week 2): define the TypedDict/Pydantic state model.
# """
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
# WHY TypedDicts: the state is plain data handed from node to node. Typed dictionaries document the shape
# without adding behaviour, and they are exactly what a LangGraph StateGraph takes as its state schema if
# the loop in graph.py is later moved to LangGraph.
"""The data passed between the agent's nodes, and what is remembered between turns."""
from __future__ import annotations

from typing import Any, TypedDict


class Slots(TypedDict, total=False):
    """What is remembered from the last answered question of a session (stored by agent/memory.py)."""

    companies: list[str]        # tickers
    fiscal_years: list[str]     # e.g. ["2025-26"]
    scope: str                  # consolidated | standalone
    metric: str | None
    item: str | None
    intent: str


class RunResult(TypedDict, total=False):
    """What the executor hands to the writer and the critic."""

    values: dict[str, dict[str, Any]]   # ticker -> {value, unit, formula, ...}
    figures: list[Any]                  # list[schemas.Figure]
    ranking: dict[str, Any]             # compare_rank output
    passages: list[dict[str, Any]]      # retrieved text for summaries
