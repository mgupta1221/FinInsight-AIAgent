"""Build eval/gold_workbook.xlsx: the sheet the team fills in to produce the gold answers.

NEW FILE (17 Nov 2026).

WHY: eval/eval_set.jsonl has one long JSON line per question and a single "gold" field. Typing 90 gold
answers into it by hand is error-prone, gives no place for the input figures and their pages, and no place
to record who entered a figure and who checked it. This script turns the 90 questions into a workbook with
one row per figure to read from a PDF. eval/compute_gold.py then turns the filled workbook back into gold
answers, so nobody edits JSON or calculates a ratio by hand.

Run from the project root (needs the figure store only for the optional page hints):
    python eval/make_gold_workbook.py            -> writes eval/gold_workbook.xlsx (refuses to overwrite)
    python eval/make_gold_workbook.py --force    -> overwrites it (typed-in values are LOST)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from openpyxl import Workbook  # noqa: E402
from openpyxl.formatting.rule import FormulaRule  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

from finsight.agent import planner  # noqa: E402
from finsight.corpus import previous_year  # noqa: E402
from finsight.schemas import AgentPlan  # noqa: E402
from finsight.tools.get_company_profile import get_company_profile  # noqa: E402
from finsight.tools.glossary import derived_inputs, get_metric, line_items, reported_metrics  # noqa: E402

EVAL_SET = ROOT / "eval" / "eval_set.jsonl"
WORKBOOK = ROOT / "eval" / "gold_workbook.xlsx"
NO_INPUT_TYPES = {"clarify", "refuse", "unanswerable"}          # their gold answer is already final in the JSONL
INPUT_HEADERS = ["question_id", "key", "what to read", "company", "fiscal_year", "scope", "read_from_report", "page_hint",
                 "unit", "value_author", "page_author", "author", "value_verifier", "page_verifier", "verifier", "match", "note"]
QUESTION_HEADERS = ["id", "type", "question", "companies", "fiscal_year", "scope", "figure_or_metric", "formula", "rank_order",
                    "gold comes from", "notes"]
KEYPOINT_HEADERS = ["question_id", "point_no", "key_point", "page", "author", "verified_by"]


def load_questions(path: Path = EVAL_SET) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def leaf_inputs(name: str) -> list[str]:
    """A statement line stays as it is; a derived input (ebit, total_debt, ...) becomes the lines it is built from."""
    if name in derived_inputs():
        return list(derived_inputs()[name]["inputs"])
    return [name]


def describe(q: dict) -> dict:
    """What a question needs: {"kind", "companies", "years", "scope", "name", "formula", "order", "inputs": [...]}.

    The figure or ratio is found with the planner's own code rules (no model call), so the workbook asks for
    exactly the inputs the agent would use. Each input is {key, label, company, fiscal_year, read_from_report}.
    """
    companies = q.get("companies") or ([q["company"]] if q.get("company") else [])
    out = {"kind": q["type"], "companies": companies, "years": [q["fiscal_year"]] if q.get("fiscal_year") else [],
           "scope": q.get("statement"), "name": q.get("metric"), "formula": "", "order": "", "inputs": []}
    if q["type"] in NO_INPUT_TYPES or q["type"] == "summary":
        return out
    if q["type"].startswith("multi"):
        out["formula"] = "numerator / denominator * 100"
        company, fy = companies[0], q["fiscal_year"]
        out["inputs"] = [{"key": k, "label": f"{k}: write the row name here", "company": company, "fiscal_year": fy,
                          "read_from_report": fy} for k in ("numerator", "denominator")]
        return out
    try:
        plan = planner.resolve(AgentPlan(intent="other"), q["question"], {})
    except Exception:  # noqa: BLE001  the planner could not place it: leave one free row per company
        plan = None
    fy = q["fiscal_year"]
    if plan is None:
        out["inputs"] = [{"key": "value", "label": "write the row name here", "company": c, "fiscal_year": fy,
                          "read_from_report": fy} for c in companies]
        out["formula"] = "value"
        return out
    out["order"] = plan.order if plan.intent == "compare_rank" else ""
    if plan.intent == "yoy":
        out["name"], out["formula"] = plan.item, "(current - previous) / previous * 100"
        for key, year in (("current", fy), ("previous", previous_year(fy))):
            for leaf in leaf_inputs(plan.item):
                out["inputs"].append({"key": f"{key}:{leaf}" if leaf != plan.item else key, "label": leaf, "company": companies[0],
                                      "fiscal_year": year, "read_from_report": fy})
        return out
    for company in companies:
        if plan.metric and plan.metric in reported_metrics():
            out["name"], out["formula"] = plan.metric, "value (as reported)"
            names = [plan.metric]
        elif plan.metric:
            spec = get_metric(plan.metric, bool(get_company_profile(company)["is_bank"]))
            out["name"], out["formula"] = plan.metric, spec["formula"]
            names = [leaf for n in spec["inputs"] for leaf in leaf_inputs(n)]
        else:
            out["name"] = plan.item
            out["formula"] = derived_inputs()[plan.item]["formula"] if plan.item in derived_inputs() else "value"
            names = leaf_inputs(plan.item)
        for n in dict.fromkeys(names):
            out["inputs"].append({"key": n, "label": n, "company": company, "fiscal_year": fy, "read_from_report": fy})
    return out


def page_hint(inp: dict, scope: str | None) -> str:
    """The page where the extractor found this row, to help the reader find it. Never the value itself."""
    if inp["label"] not in line_items():
        return ""
    try:
        from finsight.tools.get_financial_item import get_financial_item
        r = get_financial_item(inp["company"], inp["label"], inp["fiscal_year"], scope=scope or "consolidated",
                               from_report=inp["read_from_report"])
        return str(r["page"])
    except Exception:  # noqa: BLE001  not in the store, or the store is not built
        return ""


def default_unit(label: str) -> str:
    if label in reported_metrics():
        return "rupees" if reported_metrics()[label].get("unit") == "currency_per_share" else "percent"
    return ""


def build(path: Path = WORKBOOK, questions: list[dict] | None = None, hints: bool = True) -> dict:
    questions = questions if questions is not None else load_questions()
    wb = Workbook()
    font, bold = Font(name="Arial", size=10), Font(name="Arial", size=10, bold=True)
    head_font, head_fill = Font(name="Arial", size=10, bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78")
    entry_fill = PatternFill("solid", fgColor="FFF2CC")
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def sheet(ws, headers, rows, widths, entry_cols=()):
        ws.append(headers)
        for r in rows:
            ws.append(r)
        for c in ws[1]:
            c.font, c.fill, c.border = head_font, head_fill, border
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for row in ws.iter_rows(min_row=2, max_row=max(ws.max_row, 2)):
            for c in row:
                c.font, c.border = font, border
                c.alignment = Alignment(wrap_text=True, vertical="top")
                if headers[c.column - 1] in entry_cols:
                    c.fill = entry_fill
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    ws = wb.active
    ws.title = "Instructions"
    lines = [
        "FinSight gold workbook: the 90 evaluation questions",
        "",
        "Fill only the yellow cells. Everything else is filled in for you.",
        "",
        "Sheet 'Inputs': one row per figure to read from an annual report.",
        "  1. Open the report named in 'read_from_report' for that company. 'page_hint' is where our extractor found the row; it can be wrong.",
        "  2. AUTHOR: type the figure exactly as printed in 'value_author', its page (the PDF page number, as the PDF viewer counts it) in 'page_author',",
        "     the unit the page prints in 'unit', and your name in 'author'.",
        "  3. VERIFIER (a different person): read the same figure yourself WITHOUT looking at the author's cells, and fill 'value_verifier',",
        "     'page_verifier' and 'verifier'. The 'match' column then shows OK or CHECK.",
        "  4. A CHECK row is settled by a third person, who corrects the wrong cell so that both values agree.",
        "  Negative figures: type a minus sign, not brackets. Do not type commas or the rupee sign.",
        "  Units: crore, lakh, million, thousand for amounts; percent for ratios read from the text; rupees for EPS.",
        "  For the 'multihop' questions, replace the text in 'what to read' with the row names you used. Change the formula on the Questions sheet if needed.",
        "",
        "Sheet 'KeyPoints': for the 8 summary questions, write 3 to 5 key points with the page each one is on, your name, and the verifier's name.",
        "",
        "Sheet 'Questions': the list of questions. Clarify, refuse and unanswerable questions need no input; their gold answer is already final.",
        "",
        "When the sheet is filled (it can be done in parts), run:   python eval/compute_gold.py",
        "It calculates every ratio from the verified inputs with the formulas in config/glossary.yaml and writes the gold answers into eval/eval_set.jsonl.",
        "Never calculate a ratio by hand and never copy the agent's answer: gold must come from the PDF.",
    ]
    for i, text in enumerate(lines, 1):
        c = ws.cell(i, 1, text)
        c.font = Font(name="Arial", size=13, bold=True) if i == 1 else font
    ws.column_dimensions["A"].width = 150

    q_rows, in_rows, kp_rows = [], [], []
    for q in questions:
        d = describe(q)
        source = ("already final" if q["type"] in NO_INPUT_TYPES else "KeyPoints sheet" if q["type"] == "summary" else "Inputs sheet")
        q_rows.append([q["id"], q["type"], q["question"], ", ".join(d["companies"]), q.get("fiscal_year") or "", d["scope"] or "",
                       d["name"] or "", d["formula"], d["order"], source, ""])
        for inp in d["inputs"]:
            in_rows.append([q["id"], inp["key"] if len(d["companies"]) == 1 else f"{inp['company']}:{inp['key']}", inp["label"],
                            inp["company"], inp["fiscal_year"], d["scope"] or "", inp["read_from_report"],
                            page_hint(inp, d["scope"]) if hints else "", default_unit(inp["label"]), None, None, None, None, None, None, None, None])
        if q["type"] == "summary":
            kp_rows += [[q["id"], n, None, None, None, None] for n in range(1, 6)]

    ws = wb.create_sheet("Questions")
    sheet(ws, QUESTION_HEADERS, q_rows, [14, 14, 70, 26, 11, 13, 24, 44, 10, 16, 40], entry_cols=("notes",))
    ws = wb.create_sheet("Inputs")
    sheet(ws, INPUT_HEADERS, in_rows, [14, 30, 30, 13, 11, 13, 16, 9, 10, 16, 11, 14, 16, 12, 14, 9, 36],
          entry_cols=("unit", "value_author", "page_author", "author", "value_verifier", "page_verifier", "verifier", "note"))
    last = max(ws.max_row, 2)
    for r in range(2, last + 1):
        ws.cell(r, 16, f'=IF(OR(J{r}="",M{r}=""),"",IF(AND(J{r}=M{r},K{r}=N{r}),"OK","CHECK"))').font = bold
    units = DataValidation(type="list", formula1='"crore,lakh,million,thousand,percent,rupees,ratio"', allow_blank=True)
    units.add(f"I2:I{last}")
    ws.add_data_validation(units)
    ws.conditional_formatting.add(f"P2:P{last}", FormulaRule(formula=['$P2="OK"'], fill=PatternFill("solid", bgColor="C6EFCE", fgColor="C6EFCE")))
    ws.conditional_formatting.add(f"P2:P{last}", FormulaRule(formula=['$P2="CHECK"'], fill=PatternFill("solid", bgColor="FFC7CE", fgColor="FFC7CE")))
    ws.freeze_panes = "E2"
    ws = wb.create_sheet("KeyPoints")
    sheet(ws, KEYPOINT_HEADERS, kp_rows, [14, 9, 90, 8, 14, 14], entry_cols=("key_point", "page", "author", "verified_by"))
    wb.save(path)
    return {"questions": len(q_rows), "inputs": len(in_rows), "key_point_rows": len(kp_rows)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite an existing workbook (typed-in values are lost)")
    ap.add_argument("--no-hints", action="store_true", help="leave page_hint empty (does not need the figure store)")
    args = ap.parse_args()
    if WORKBOOK.exists() and not args.force:
        sys.exit(f"{WORKBOOK.relative_to(ROOT)} already exists. Use --force to overwrite it; values typed into it would be lost.")
    print(build(hints=not args.no_hints), "->", WORKBOOK.relative_to(ROOT))
