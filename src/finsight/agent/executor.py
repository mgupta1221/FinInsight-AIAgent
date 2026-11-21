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
from finsight.corpus import fiscal_years, fix_glyphs   # fix_glyphs: 19 Nov 2026
from finsight.safety.sanitiser import sanitise
from finsight.schemas import AgentPlan, AgentStep, Extracted, Figure, RatioParts   # RatioParts: 19 Nov 2026
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
# CHANGED (18 Nov 2026): each topic now also names the report sections where it is normally discussed.
# OLD entries were (pattern, extra search words). WHY: with section labels that can be trusted (ingest/sections.py)
# a summary can PREFER the right part of the report: a strategy summary should come from the overview and the
# MD&A, not from a note on capital management. It is a preference, not a filter: if those sections return
# nothing, passages from elsewhere are still used.
SUMMARY_TOPICS = [
    (r"risk", "principal risks risk management mitigation risks and opportunities",
     ["risk", "mdna", "directors_report", "overview"]),
    (r"strateg|outlook|priorit|future|plan", "strategy strategic priorities outlook growth opportunities way forward",
     ["overview", "mdna", "directors_report"]),
    (r"commentary|management discussion|md&a|mdna", "management discussion and analysis review of performance operating environment",
     ["mdna", "directors_report", "overview"]),
    (r"performance|results|business|financial review|growth", "revenue growth turnover profit margin volume growth segment performance financial highlights year in review",
     ["mdna", "directors_report", "overview", "highlights"]),
]


class Escalate(Exception):
    """The agent cannot complete the task reliably; hand back to the user with the reason."""


class NotApplicable(ToolError):
    """NEW (19 Nov 2026, later). The report itself says the thing asked about does not exist for this company
    (Infosys: "The Group has no outstanding borrowings"). Not a failure to find a figure: an answer in words."""

    def __init__(self, message: str, citation: str):
        super().__init__(message)
        self.citation = citation


# NEW (19 Nov 2026, later): helpers for text_ratio(). See the notes there.
_NUMERIC = re.compile(r"^\(?-?[\d.]+\)?%?$")
_GENERIC = set("""share proportion portion percentage percent per cent part total came come comes coming due within one year
    years revenue revenues sales income business segment segments advances gross net company bank group its their
    report reported amount value figure ratio rate fy""".split())


def _row_of(flat: str, digits: str):
    """Where a printed number sits in its table row: (row label, numbers of the row, position in the row).

    "FMCG - Others 24203.75 6.00 24209.75 21975.28 ..." and "24209.75" -> ("FMCG - Others", [...], 2).
    """
    tokens = flat.split()
    at = next((i for i, t in enumerate(tokens) if t.strip("()%") == digits), None)
    if at is None:
        return None
    lo = hi = at
    while lo > 0 and (_NUMERIC.match(tokens[lo - 1]) or tokens[lo - 1] in "-–—"):
        lo -= 1
    while hi + 1 < len(tokens) and (_NUMERIC.match(tokens[hi + 1]) or tokens[hi + 1] in "-–—"):
        hi += 1
    while lo < at and tokens[lo] in "-–—":                      # a dash that belongs to the label ("FMCG - Others")
        lo += 1
    label, k = [], lo - 1
    while k >= 0 and len(label) < 7 and not re.search(r"\d", tokens[k]):
        label.insert(0, tokens[k])
        k -= 1
    return " ".join(label), tokens[lo:hi + 1], at - lo


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
            # OLD: return self.statement_figure(company, name, fy, from_report, name=label)
            # NEW (19 Nov 2026): a line with a `fallback` in the glossary is built from its parts when the
            # statement does not print it (tax expense = current tax + deferred tax). See config/glossary.yaml.
            fallback = line_items()[name].get("fallback")
            try:
                v = self.statement_figure(company, name, fy, from_report, name=label)
                return abs(v) if line_items()[name].get("always_positive") else v      # see tax_from_parts in the glossary
            except ToolError:
                if not fallback:
                    raise
                self.trace.append({"note": f"no '{name}' line in the statement; built from {derived_inputs()[fallback]['inputs']}"})
                name = fallback
        spec = derived_inputs().get(name)
        if spec is None:
            raise ToolError(f"'{name}' is not a statement line and has no derivation in the glossary")
        # OLD: parts = {k: self.statement_figure(company, k, fy, from_report) for k in spec["inputs"]}
        # NEW (19 Nov 2026): inputs marked `optional` in the glossary count as zero when the statement has no such
        # line, as long as at least one of them is found.
        # WHY: Tech Mahindra's balance sheet has ONE "Borrowings" line (current); there is no non-current one. Total
        #      debt = non-current + current then failed on the missing line, and so did "Which had the higher
        #      debt-to-equity ratio, Wipro or Tech Mahindra?". A company with no borrowings line at all still
        #      raises the error (the agent does not invent a zero).
        optional, parts, missing = set(spec.get("optional", [])), {}, []
        for k in spec["inputs"]:
            try:
                parts[k] = self.statement_figure(company, k, fy, from_report)
            except ToolError:
                if k not in optional:
                    raise
                parts[k] = 0.0
                missing.append(k)
        if missing and len(missing) == len(optional):
            raise ToolError(f"no figure for '{name}' ({company} FY{fy} {self.plan.scope})")
        if missing:
            self.trace.append({"note": f"no line for {missing} in the statement; counted as zero"})
            if spec.get("single_name"):                        # one line only: show it under its plain name
                self.figures[-1].name = spec["single_name"]
        value = self.call("evaluate_expression", expr=spec["formula"], variables=parts)
        self.trace.append({"note": f"{name} = {spec['formula']} = {value:,.2f} crore"})
        # OLD: return value
        if spec.get("always_positive") and value < 0:              # NEW (19 Nov 2026): see tax_from_parts in the glossary
            self.trace.append({"note": f"{name} is printed as a deduction (negative); taken as {abs(value):,.2f}"})
            value = abs(value)
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
            text, scope = fix_glyphs(h["text"]), None                # 19 Nov 2026: repair private-font digits (corpus.fix_glyphs)
            if text.startswith("[") and "\n" in text:             # chunk header "[Company | FY.. | p214]" is not report text
                # NEW (19 Nov 2026): the header also says whether the page is standalone or consolidated; kept for text_ratio()
                scope = next((w for w in ("standalone", "consolidated") if w in text.split("\n", 1)[0]), None)
                text = text.split("\n", 1)[1]
            passages.append({"page": h["page"], "citation": h["citation"], "text": text, "score": h.get("score"),
                             "section": h.get("section"), "scope": scope})   # 18 Nov 2026: section kept, for summarise()
        self.trace.append({"tool": "search_report", "args": {"query": query, "company": company, "fiscal_year": fy},
                           "result": [{"page": p["page"], "citation": p["citation"]} for p in passages]})
        if not passages:
            raise ToolError(f"nothing found for '{query}' in {company} FY{fy}")
        return passages

    def reported_figure(self, company: str, metric: str, fy: str) -> float:
        """A ratio the company states itself: search the report, let the model point at it, then verify in code."""
        spec = reported_metrics()[metric]
        # OLD: passages = self.search(spec["search"], company, fy, top_k=4)
        # NEW (19 Nov 2026): more passages, the pages of the asked scope first, and a direct read by pattern.
        # WHY: see `patterns` in config/glossary.yaml (Axis Bank gross NPA ratio). With 4 passages the note that
        #      prints the ratio was often not among them.
        passages = self.search(spec["search"], company, fy, top_k=8)
        passages = [p for p in passages if p.get("scope") == self.plan.scope] + [p for p in passages if p.get("scope") != self.plan.scope]
        # When the line is printed on several pages, the page of the asked scope wins, then the EARLIEST page.
        # WHY the earliest: Kotak's FY2024-25 notes print the table twice, this year's on page 241 (1.42%) and last
        #      year's on page 242 (1.39%). The current year always comes first.
        for rx in spec.get("patterns", []):
            hits = [(p, m) for p in passages for m in [re.search(rx, sanitise(p["text"])[0], re.I)] if m]
            if hits:
                same = [h for h in hits if h[0].get("scope") == self.plan.scope] or hits
                p, m = min(same, key=lambda h: h[0]["page"])
                value = float(m.group(1))
                self.trace.append({"node": "extract", "metric": metric, "note": f"read by pattern on {p['citation']}: {m.group(0)[:120]}"})
                self.figures.append(Figure(name=metric, company=company, fiscal_year=fy, value=value, unit=spec["unit"],
                                           page=p["page"], citation=p["citation"]))
                return value
        passages = passages[:5]
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

    # NEW (19 Nov 2026): a share / percentage that is not in the glossary, worked out from the report text.
    # WHY: see planner.TEXT_RATIO. This is the "multi-step" path: search the notes, pick the two rows, check
    #      them, divide. The model only POINTS at numbers; code checks that each one is printed on the cited
    #      page and does the division. Both numbers must come from the same page, so they are in the same unit
    #      and from the same table. If the report states the percentage itself, that printed figure is used.
    #      What code cannot check is whether the model picked the right ROWS and the right year's column, so
    #      the answer names the two rows and carries a note asking the reader to confirm them.
    def text_ratio(self, company: str, fy: str, question: str) -> dict:
        found = self.search(question, company, fy, top_k=8)
        found = [p for p in found if p.get("scope") == self.plan.scope] + [p for p in found if p.get("scope") != self.plan.scope]
        pages: dict[str, dict] = {}                              # passages of one page are read together
        for p in found:
            text, n = sanitise(p["text"])
            if n:
                self.trace.append({"note": f"sanitiser removed {n} instruction-like sentence(s) from {p['citation']}"})
            page = pages.setdefault(p["citation"], {"page": p["page"], "citation": p["citation"], "scope": p.get("scope"), "text": ""})
            page["text"] = (page["text"] + " " + text).strip()[:2600]
        pages = dict(list(pages.items())[:4])
        system = ("You read excerpts of a company's annual report to answer a 'what share' or 'what percentage' question. "
                  "Reply with JSON. If an excerpt states the percentage itself, put that number in stated_quote and say what it "
                  "is in numerator_label. Otherwise give the two numbers needed: numerator_label and numerator_quote (the part), "
                  "denominator_label and denominator_quote (the whole). Copy each number exactly as printed. Both numbers must "
                  "come from the SAME excerpt, the same column and the requested year (the current year, not the previous "
                  "year). citation is the bracketed id above that excerpt. If the excerpts do not contain the numbers, set "
                  "found to false. Never calculate and never guess.")
        year_end = "31 March 20" + fy[-2:]
        user = (f"Question: {question}\nCompany: {company}. Year: FY{fy} (year ended {year_end}, column headed 20{fy[-2:]}).\n\n"
                + "\n\n".join(f"[{c}]\n{p['text']}" for c, p in pages.items()))
        parts = self.llm.json(system, user, RatioParts, max_tokens=200)
        self.trace.append({"node": "extract", "metric": "share_from_report", "model_reply": parts.model_dump()})
        page = pages.get(parts.citation.strip("[] ")) or (next(iter(pages.values())) if len(pages) == 1 else None)
        fail = ToolError(f"could not find verifiable numbers for this share in the retrieved pages of {company} FY{fy}")
        if not parts.found or page is None:
            raise fail
        flat = page["text"].replace(",", "")

        # NEW (19 Nov 2026, later): the number must be ABOUT what was asked.
        # WHY: "State Bank of India's restructured advances as a percentage of gross advances" was answered with
        #      "Green Advances 2.83%". The figure was printed on the page, so the old check passed, but it is a
        #      different thing. Now the words that make the question specific ("restructured"; "international";
        #      "FMCG", "Others") must stand close to the number on the page, or in the label of its table row.
        from finsight.agent.planner import _FILLER
        from finsight.tools.company_match import _aliases
        names = {w for n in _aliases().get(get_company_profile(company)["ticker"], []) for w in re.findall(r"[a-z]+", n.lower())}
        specific = [w for w in dict.fromkeys(re.findall(r"[a-z]+", question.lower()))
                    if len(w) > 2 and w not in _FILLER and w not in _GENERIC and w not in names]

        def about(digits: str, label: str = "") -> bool:
            m = re.search(rf"(?<![\d.]){re.escape(digits)}(?![\d])", flat)
            near = (label + " " + flat[max(0, m.start() - 300):m.end() + 120]).lower() if m else label.lower()
            return all(w in near for w in specific)

        def printed(quote: str) -> float | None:
            digits = re.sub(r"[^\d.]", "", quote).strip(".")
            if not digits or re.search(rf"(?<![\d.]){re.escape(digits)}(?![\d])", flat) is None:
                return None
            try:
                return float(digits)
            except ValueError:
                return None

        def tidy(label: str, default: str) -> str:
            return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z &/,()'-]", " ", label)).strip()[:70] or default

        def fig(name: str, value: float, unit: str) -> None:
            self.figures.append(Figure(name=name, company=company, fiscal_year=fy, value=value, unit=unit,
                                       page=page["page"], citation=page["citation"]))
        stated = printed(parts.stated_quote) if parts.stated_quote else None
        if stated is not None and not about(re.sub(r"[^\d.]", "", parts.stated_quote).strip(".")):
            self.trace.append({"note": f"the percentage the model pointed at is not about {specific}; not used"})
            raise fail
        if stated is not None and 0 < stated <= 100:
            label = tidy(parts.numerator_label, "the share")
            fig(f"stated: {label}", stated, "percent")
            return {"metric": "share_from_report", "value": stated, "unit": "percent", "formula": None,
                    "labels": [label], "page_scope": page["scope"]}
        num, den = printed(parts.numerator_quote), printed(parts.denominator_quote)
        # NEW (19 Nov 2026, later): both numbers must come from the same COLUMN, and the rows are named from the page.
        # WHY: for the ITC segment share the model took the part from the "Total" column (24,209.75) and the whole
        #      from the "External" column (80,867.49): 29.94%, a mix of two columns. Each number is now located
        #      in its table row. If the two rows have the same number of columns and the positions differ, the
        #      whole is taken from the same position as the part (90,713.20 -> 26.69%). The labels shown in the
        #      answer are the row names printed on the page ("FMCG - Others", "Segment Total"), not the model's
        #      wording ("Segment Revenue", "Total Segment Revenue").
        row_n = _row_of(flat, re.sub(r"[^\d.]", "", parts.numerator_quote).strip(".")) if num is not None else None
        row_d = _row_of(flat, re.sub(r"[^\d.]", "", parts.denominator_quote).strip(".")) if den is not None else None
        if row_n and row_d and len(row_n[1]) == len(row_d[1]) >= 2 and row_n[2] != row_d[2]:
            try:
                moved = float(row_d[1][row_n[2]].strip("()%"))
                self.trace.append({"note": f"the whole was read from another column ({den:,.2f}); taken from the same column as the part ({moved:,.2f})"})
                den = moved
            except ValueError:
                den = None
        if num is not None and not about(re.sub(r"[^\d.]", "", parts.numerator_quote).strip("."), row_n[0] if row_n else ""):
            self.trace.append({"note": f"the part the model pointed at is not about {specific}; not used"})
            raise fail
        if row_n and re.search(r"[A-Za-z]", row_n[0]):
            parts.numerator_label = row_n[0]
        if row_d and re.search(r"[A-Za-z]", row_d[0]):
            parts.denominator_label = row_d[0]
        if num is None or den is None or den == 0 or num > den:
            self.trace.append({"note": "the numbers the model pointed at are not printed on the cited page, or the part is larger than the whole"})
            raise fail
        n_label, d_label = tidy(parts.numerator_label, "the part"), tidy(parts.denominator_label, "the whole")
        fig(f"numerator: {n_label}", num, "as printed")
        fig(f"denominator: {d_label}", den, "as printed")
        value = self.call("evaluate_expression", expr="numerator / denominator * 100", variables={"numerator": num, "denominator": den})
        return {"metric": "share_from_report", "value": round(value, 4), "unit": "percent", "formula": "numerator / denominator * 100",
                "inputs": {"numerator": num, "denominator": den}, "labels": [n_label, d_label], "page_scope": page["scope"]}

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
        elif plan.metric == "share_from_report":                  # NEW (19 Nov 2026): see text_ratio() above
            self.values[company] = self.text_ratio(company, fy, plan.topic)
        elif plan.metric and plan.metric in reported_metrics():
            self.values[company] = {"metric": plan.metric, "value": self.reported_figure(company, plan.metric, fy),
                                    "unit": reported_metrics()[plan.metric]["unit"], "formula": None}
        elif plan.metric:
            spec = get_metric(plan.metric, is_bank)
            # OLD: inputs = {k: self.input_value(company, k, fy) for k in spec["inputs"]}
            # NEW (19 Nov 2026, later): a company with no borrowings at all gets an answer in words.
            # WHY: "What share of Infosys' total borrowings was due within one year?" ended in "no figure for
            #      'current_borrowings'", which reads like a fault. Infosys has no borrowings, and its report
            #      says so. When the borrowings lines are missing, the report text is searched for that statement.
            try:
                inputs = {k: self.input_value(company, k, fy) for k in spec["inputs"]}
            except ToolError:
                if plan.metric == "short_term_borrowings_share":
                    self.no_borrowings(company, fy)
                raise
            out = self.call("calculate", metric=plan.metric, inputs=inputs, is_bank=is_bank)
            self.values[company] = {**out, "value": round(out["value"], 4)}
        else:
            v = self.input_value(company, plan.item, fy)
            last = self.figures[-1].unit.lower()
            unit = "crore" if (plan.item in derived_inputs() or last in AMOUNT_UNITS) else self.figures[-1].unit
            self.values[company] = {"metric": None, "value": round(v, 2), "unit": unit, "formula": None}

    def no_borrowings(self, company: str, fy: str) -> None:
        """Raise NotApplicable if the report states that the company has no borrowings (19 Nov 2026, later)."""
        try:
            found = self.search("no outstanding borrowings liquidity working capital", company, fy, top_k=6)
        except ToolError:
            return
        for p in found:
            if re.search(r"\bno (outstanding )?(borrowings|debt)\b|not taken any loans or other borrowings|\bdebt[- ]free\b", p["text"], re.I):
                raise NotApplicable(f"{get_company_profile(company)['name']} states in its FY{fy} report that it has no outstanding "
                                    f"borrowings ({p['citation']}), so there is no share of borrowings to work out", p["citation"])

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
        query, preferred = topic, []
        for pattern, extra, sections in SUMMARY_TOPICS:
            if re.search(pattern, topic.lower()):
                query, preferred = f"{topic} {extra}", sections
                break
        found = self.search(query, company, fiscal_year, top_k=20)      # OLD: top_k=10, used in search order
        ordered = [p for p in found if p.get("section") in preferred] + [p for p in found if p.get("section") not in preferred]
        passages, pages = [], set()
        for p in ordered:
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
