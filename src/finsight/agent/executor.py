# ORIGINAL PLACEHOLDER (kept):
# """Executor node (code): runs the plan's tool steps; each observation can trigger a re-plan
# (missing item -> search_report; unit mismatch -> normalise_units). Enforces the step cap.
# TODO (Week 2)."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026).
"""Executor node (code). Runs the plan's steps with the tools.

Every tool call and its result is appended to the trace. A ToolError is recorded and re-raised to the loop,
which turns it into an "escalated" answer naming the pages found so far; a figure is never guessed.
Enforces: the step cap (settings.max_steps), a tool-call cap, and no repeated identical call.

WHY a "step" is one company's computation and not one tool call: ranking five companies by operating
margin needs about 25 tool calls (four figures each, conversions, a calculation). Counted as tool calls it
could never fit a 10-step cap; counted as "compute the value for company X" it is 5 steps plus the ranking.
"""
from __future__ import annotations

import json
import re

from finsight.config import settings
from finsight.corpus import fiscal_years
from finsight.safety.sanitiser import sanitise
from finsight.schemas import AgentPlan, AgentStep, Extracted, Figure
from finsight.tools.base import ToolError
from finsight.tools.calculate import calculate, evaluate_expression
from finsight.tools.compare_rank import compare_rank
from finsight.tools.get_company_profile import get_company_profile
from finsight.tools.get_financial_item import get_financial_item
from finsight.tools.glossary import derived_inputs, get_metric, line_items, reported_metrics
from finsight.tools.normalise_units import normalise
from finsight.tools.search_report import search_report

MAX_TOOL_CALLS = 60
AMOUNT_UNITS = {"crore", "crores", "lakh", "lakhs", "million", "billion", "thousand", "rupees"}
TOOLS = {"get_financial_item": get_financial_item, "normalise_units": normalise, "calculate": calculate,
         "compare_rank": compare_rank, "evaluate_expression": evaluate_expression}


# Topic of a summary -> the words such a section of an annual report really uses (17 Nov 2026; see summarise()).
SUMMARY_TOPICS = [
    (r"risk", "principal risks risk management mitigation risks and opportunities"),
    (r"strateg|outlook|priorit|future|plan", "strategy strategic priorities outlook growth opportunities way forward"),
    (r"commentary|management discussion|md&a|mdna", "management discussion and analysis review of performance operating environment"),
    (r"performance|results|business|financial review|growth", "revenue growth turnover profit margin volume growth segment performance financial highlights year in review"),
]


class Escalate(Exception):
    """The agent cannot complete the task reliably; hand back to the user with the reason."""


class Run:
    def __init__(self, plan: AgentPlan, llm, trace: list[dict]):
        self.plan, self.llm, self.trace = plan, llm, trace
        self.calls: dict[str, object] = {}
        self.figures: list[Figure] = []
        self.values: dict[str, dict] = {}
        self.result: dict = {}

    def call(self, tool: str, **args):
        key = tool + json.dumps(args, sort_keys=True, default=str)
        if key in self.calls:                                    # identical call already made: reuse, do not loop
            self.trace.append({"tool": tool, "args": args, "note": "repeat blocked; earlier result reused"})
            return self.calls[key]
        if len(self.calls) >= MAX_TOOL_CALLS:
            raise Escalate("tool-call limit reached")
        try:
            out = TOOLS[tool](**args)
        except ToolError as e:
            self.trace.append({"tool": tool, "args": args, "error": str(e)})
            raise
        self.calls[key] = out
        self.trace.append({"tool": tool, "args": args, "result": out})
        return out

    # ---- figures -------------------------------------------------------------------------------
    def statement_figure(self, company: str, item: str, fy: str, from_report: str | None = None, name: str | None = None) -> float:
        """One statement line, converted to Rs crore, recorded with its page."""
        r = self.call("get_financial_item", company=company, line_item=item, fiscal_year=fy, scope=self.plan.scope,
                      from_report=from_report)
        self.figures.append(Figure(name=name or item, company=company, fiscal_year=fy, value=r["value"], unit=r["unit"],
                                   page=r["page"], citation=r["citation"]))
        unit = str(r["unit"]).lower()
        if unit.endswith("?") or unit in ("", "unknown"):
            self.trace.append({"note": f"unit '{r['unit']}' on {r['citation']} was not read from the page"})
            raise ToolError(f"unit '{r['unit']}' is not confirmed; a person must check {r['citation']}")
        if unit not in AMOUNT_UNITS:
            return r["value"]
        return self.call("normalise_units", value=r["value"], from_unit=unit, to_unit="crore")["value"]

    def input_value(self, company: str, name: str, fy: str, from_report: str | None = None, label: str | None = None) -> float:
        """A formula input: a statement line, or an abstract input built from statement lines (glossary derived_inputs)."""
        if name in line_items():
            return self.statement_figure(company, name, fy, from_report, name=label)
        spec = derived_inputs().get(name)
        if spec is None:
            raise ToolError(f"'{name}' is not a statement line and has no derivation in the glossary")
        parts = {k: self.statement_figure(company, k, fy, from_report) for k in spec["inputs"]}
        value = self.call("evaluate_expression", expr=spec["formula"], variables=parts)
        self.trace.append({"note": f"{name} = {spec['formula']} = {value:,.2f} crore"})
        return value

    @staticmethod
    def _focus(text: str, keywords: list[str], window: int = 320) -> str:
        """Keep only the parts of a passage around the keywords, so a small model is not lost in a long page."""
        low, spans = text.lower(), []
        for k in keywords:
            for m in re.finditer(re.escape(k), low):
                spans.append((max(0, m.start() - window), min(len(text), m.end() + window)))
        if not spans:
            return ""
        spans.sort()
        merged = [list(spans[0])]
        for a, b in spans[1:]:
            if a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        return " ... ".join(text[a:b] for a, b in merged)[:1600]

    def search(self, query: str, company: str, fy: str, top_k: int) -> list[dict]:
        """search_report, with the chunk's metadata header removed from the text and failures turned into ToolError."""
        try:
            hits = search_report(query, company=company, fiscal_year=fy, top_k=top_k)
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001  (index missing, Qdrant down)
            self.trace.append({"tool": "search_report", "args": {"query": query, "company": company, "fiscal_year": fy},
                               "error": str(e)[:200]})
            raise ToolError(f"search is unavailable ({str(e)[:80]}); has ingestion been run?") from e
        passages = []
        for h in hits:
            text = h["text"]
            if text.startswith("[") and "\n" in text:             # chunk header "[Company | FY.. | p214]" is not report text
                text = text.split("\n", 1)[1]
            passages.append({"page": h["page"], "citation": h["citation"], "text": text, "score": h.get("score")})
        self.trace.append({"tool": "search_report", "args": {"query": query, "company": company, "fiscal_year": fy},
                           "result": [{"page": p["page"], "citation": p["citation"]} for p in passages]})
        if not passages:
            raise ToolError(f"nothing found for '{query}' in {company} FY{fy}")
        return passages

    def reported_figure(self, company: str, metric: str, fy: str) -> float:
        """A ratio the company states itself: search the report, let the model point at it, then verify in code."""
        spec = reported_metrics()[metric]
        passages = self.search(spec["search"], company, fy, top_k=4)
        blocks, removed = [], 0
        for p in passages:
            text, n = sanitise(p["text"])
            removed += n
            snippet = self._focus(text, spec.get("keywords", []))
            if snippet:
                blocks.append(f"[{p['citation']}]\n{snippet}")
        if removed:
            self.trace.append({"note": f"sanitiser removed {removed} instruction-like sentence(s) from retrieved text"})
        if not blocks:
            self.trace.append({"note": f"no retrieved passage mentions {spec.get('keywords')}"})
            raise ToolError(f"could not find {metric.replace('_', ' ')} for {company} FY{fy} in the retrieved pages")
        year_end = "31 March 20" + fy[-2:]
        system = ("You read excerpts of a company's annual report and pick out ONE figure. Reply with JSON: found (true/false), "
                  "value (the number only), quote (the number exactly as printed, digits and decimal point only), "
                  "citation (the bracketed id above the excerpt it came from). The figure may be worded differently from its name. "
                  "Take the figure for the requested year (the current year), not the previous year. "
                  "If the excerpts do not state it, set found to false. Never calculate and never guess.")
        user = (f"Figure wanted: {metric.replace('_', ' ')} of {company} for FY{fy} (year ended {year_end}).\n"
                f"Meaning: {spec.get('hint', '')}.\n\n" + "\n\n".join(blocks))
        ex = self.llm.json(system, user, Extracted, max_tokens=120)
        self.trace.append({"node": "extract", "metric": metric, "model_reply": ex.model_dump()})
        cited = ex.citation.strip("[] ")
        page = next((p for p in passages if p["citation"] == cited), None)
        if page is None and ex.found and len({p["citation"] for p in passages}) == 1:
            page = passages[0]
        digits = re.sub(r"[^\d.]", "", ex.quote).strip(".") or (f"{ex.value:g}" if ex.value is not None else "")
        printed = bool(page) and bool(digits) and re.search(rf"(?<![\d.]){re.escape(digits)}(?![\d])", page["text"].replace(",", "")) is not None
        if not ex.found or ex.value is None or not printed:
            self.trace.append({"note": f"reported {metric} for {company} could not be verified on a retrieved page"})
            raise ToolError(f"could not find a verifiable {metric.replace('_', ' ')} for {company} FY{fy}")
        try:
            if abs(float(digits) - float(ex.value)) > 1e-6:
                raise ValueError
        except ValueError:
            raise ToolError(f"the model's value for {metric} does not match its own quote") from None
        self.figures.append(Figure(name=metric, company=company, fiscal_year=fy, value=float(ex.value), unit=spec["unit"],
                                   page=page["page"], citation=page["citation"]))
        return float(ex.value)

    # ---- steps ---------------------------------------------------------------------------------
    def value_for_company(self, company: str) -> None:
        plan, fy = self.plan, self.plan.fiscal_years[-1]
        is_bank = bool(get_company_profile(company)["is_bank"])
        if plan.metric == "yoy_change":
            prev = plan.fiscal_years[0]
            report = fy if fy in fiscal_years() else None          # both years from the later report (SPEC 4)
            cur_v = self.input_value(company, plan.item, fy, report, label="current")
            prev_v = self.input_value(company, plan.item, prev, report, label="previous")
            out = self.call("calculate", metric="yoy_change", inputs={"current": cur_v, "previous": prev_v}, is_bank=is_bank)
            self.values[company] = {**out, "value": round(out["value"], 4), "current": cur_v, "previous": prev_v,
                                    "absolute_change": round(cur_v - prev_v, 4)}
        elif plan.metric and plan.metric in reported_metrics():
            self.values[company] = {"metric": plan.metric, "value": self.reported_figure(company, plan.metric, fy),
                                    "unit": reported_metrics()[plan.metric]["unit"], "formula": None}
        elif plan.metric:
            spec = get_metric(plan.metric, is_bank)
            inputs = {k: self.input_value(company, k, fy) for k in spec["inputs"]}
            out = self.call("calculate", metric=plan.metric, inputs=inputs, is_bank=is_bank)
            self.values[company] = {**out, "value": round(out["value"], 4)}
        else:
            v = self.input_value(company, plan.item, fy)
            last = self.figures[-1].unit.lower()
            unit = "crore" if (plan.item in derived_inputs() or last in AMOUNT_UNITS) else self.figures[-1].unit
            self.values[company] = {"metric": None, "value": round(v, 2), "unit": unit, "formula": None}

    def summarise(self, company: str, fiscal_year: str, topic: str) -> None:
        # CHANGED (17 Nov 2026). OLD:
        #     passages = []
        #     for p in self.search(topic, company, fiscal_year, top_k=3):
        #         ...
        # WHY: the topic "Business Performance" was searched with exactly those two words, and the search matches
        #      words. It returned pages on employee PERFORMANCE management and PERFORMANCE share plans, so the
        #      summary was about HR, not about how the business did. Two changes:
        #      1. the topic is widened with the words such a section really uses (SUMMARY_TOPICS below), which on
        #         the same report brings up the CEO's statement, the letter to shareholders and the MD&A;
        #      2. at most one passage per page, up to 4 pages, so one page cannot fill the whole summary.
        query = topic
        for pattern, extra in SUMMARY_TOPICS:
            if re.search(pattern, topic.lower()):
                query = f"{topic} {extra}"
                break
        passages, pages = [], set()
        for p in self.search(query, company, fiscal_year, top_k=10):
            if p["page"] in pages:
                continue
            pages.add(p["page"])
            text, n = sanitise(p["text"])
            if n:
                self.trace.append({"note": f"sanitiser removed {n} instruction-like sentence(s) from {p['citation']}"})
            passages.append({"citation": p["citation"], "page": p["page"], "text": text[:1500]})
            if len(passages) == 4:
                break
        self.result["passages"] = passages

    def execute(self, steps: list[AgentStep]) -> dict:
        if len(steps) > settings.max_steps:
            raise Escalate(f"the plan needs {len(steps)} steps; the limit is {settings.max_steps}. Ask about fewer companies.")
        for n, step in enumerate(steps, 1):
            self.trace.append({"step": n, "do": step.tool, "args": step.args})
            if step.tool == "value_for_company":
                self.value_for_company(**step.args)
            elif step.tool == "summarise":
                self.summarise(**step.args)
            elif step.tool == "compare_rank":
                self.result["ranking"] = self.call("compare_rank", values={c: v["value"] for c, v in self.values.items()}, **step.args)
            else:
                raise Escalate(f"unknown step '{step.tool}'")
        self.result.update(values=self.values, figures=self.figures)
        return self.result
