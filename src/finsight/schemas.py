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


# =====================================================================================================
# ADDED (agent layer, 13 Nov 2026). The models above are unchanged and still importable.
#
# WHY new models instead of editing Plan / Answer above:
#   * The planner works in two stages. The MODEL only fills slots (who, which year, which figure); CODE
#     then validates them and builds the steps. `Plan` above asks the model to also write the tool steps,
#     which an 8B model does unreliably. `AgentPlan` holds slots only; `AgentStep` is built in code.
#   * `Answer` above has no place for the status, the value and unit, a ranking, key points, the clarifying
#     question, the refusal reason, the trace or the token count, all of which the SPEC answer format and
#     the evaluation need. `AgentAnswer` is a superset of it.
#   * `Figure` extends `FigureInput` with the company and fiscal year (needed when several companies or
#     two years are involved) and allows a missing page while a run is being escalated.
#   * `Draft`, `SummaryDraft` and `Extracted` are the three small things the model is asked to return.
# =====================================================================================================
from typing import Literal, Optional  # noqa: E402

AgentIntent = Literal["fact", "ratio", "yoy", "compare_rank", "summary", "other"]
AgentStatus = Literal["answered", "clarify", "refused", "escalated"]


class AgentPlan(BaseModel):
    """Slots the planner model extracts. Fiscal years are strings like "2025-26"."""

    intent: AgentIntent
    companies: list[str] = Field(default_factory=list, description="company names or tickers as written")
    fiscal_years: list[str] = Field(default_factory=list, description='e.g. "2025-26"')
    scope: Optional[Literal["consolidated", "standalone"]] = None
    metric: Optional[str] = Field(None, description="glossary metric id, if a ratio is asked for")
    item: Optional[str] = Field(None, description="statement line id, if a reported figure is asked for")
    topic: Optional[str] = Field(None, description="for summary questions: what to summarise")
    order: Optional[Literal["highest", "lowest"]] = None
    is_follow_up: bool = False


class AgentStep(BaseModel):
    """One step of the executable plan, built in code (not by the model)."""

    tool: str
    args: dict = Field(default_factory=dict)


class Figure(BaseModel):
    """One figure behind an answer, with where it came from."""

    name: str
    company: str
    fiscal_year: str
    value: float
    unit: str
    page: Optional[int] = None
    citation: Optional[str] = None


class Draft(BaseModel):
    """Writer model output: wording only. The numbers are checked by the critic."""

    answer: str
    caveats: list[str] = Field(default_factory=list)


class KeyPoint(BaseModel):
    point: str
    citation: str


class SummaryDraft(BaseModel):
    answer: str
    key_points: list[KeyPoint] = Field(default_factory=list)


class Extracted(BaseModel):
    """A reported figure the model points at in retrieved text (verified in code afterwards)."""

    found: bool
    value: Optional[float] = None
    quote: str = Field("", description="the number exactly as printed on the page")
    citation: str = ""


class RatioParts(BaseModel):
    """NEW (19 Nov 2026). The numbers behind a "what share / what percentage" question, pointed at by the model in
    retrieved text and verified in code afterwards (executor.text_ratio)."""

    found: bool
    stated_quote: str = Field("", description="the percentage exactly as printed, if the report states it itself")
    numerator_label: str = ""
    numerator_quote: str = Field("", description="the part, exactly as printed")
    denominator_label: str = ""
    denominator_quote: str = Field("", description="the whole, exactly as printed")
    citation: str = ""


class AgentAnswer(BaseModel):
    """The final answer object returned by finsight.agent.graph.run()."""

    status: AgentStatus
    intent: Optional[str] = None
    answer: str = ""
    value: Optional[float] = None
    unit: Optional[str] = None
    companies: list[str] = Field(default_factory=list)
    fiscal_years: list[str] = Field(default_factory=list)
    scope: Optional[str] = None
    metric: Optional[str] = None
    formula: Optional[str] = None
    inputs: list[Figure] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)
    answer_company: Optional[str] = None
    key_points: list[KeyPoint] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    verified: bool = False
    clarifying_question: Optional[str] = None
    refusal_reason: Optional[str] = None
    trace: list[dict] = Field(default_factory=list)
    tokens_used: int = 0


class Verdict(BaseModel):
    """Critic result (same idea as CriticVerdict above; kept separate so the two can evolve independently)."""

    ok: bool
    reasons: list[str] = Field(default_factory=list)
