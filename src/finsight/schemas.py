"""Pydantic models for every agent output and shared data object.

These are the strict shapes that the LLM must produce (validated via instructor, with retries),
so malformed model replies are caught instead of flowing downstream.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Intent(str, Enum):
    fact = "fact"
    ratio = "ratio"
    yoy = "yoy"
    compare = "compare"
    rank = "rank"
    summary = "summary"


class Scope(str, Enum):
    consolidated = "consolidated"
    standalone = "standalone"


class Status(str, Enum):
    answered = "answered"
    clarify = "clarify"
    refused = "refused"
    escalated = "escalated"


class PlanStep(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)
    reason: str = ""


class Plan(BaseModel):
    """Planner output."""

    intent: Intent
    companies: list[str] = Field(default_factory=list)
    fiscal_years: list[str] = Field(default_factory=list)
    statement: Scope = Scope.consolidated
    metric: str | None = None
    items_needed: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)
    clarify_question: str | None = None  # set when a slot is missing/ambiguous


class FigureInput(BaseModel):
    """One input figure behind an answer, with its provenance."""

    name: str
    value: float
    unit: str
    page: int
    citation: str  # e.g. INFY-FY2526-p214


class Answer(BaseModel):
    """Writer output."""

    answer: str
    formula: str | None = None
    inputs: list[FigureInput] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class CriticVerdict(BaseModel):
    """Critic output."""

    ok: bool
    reasons: list[str] = Field(default_factory=list)  # why it failed, if ok is False
