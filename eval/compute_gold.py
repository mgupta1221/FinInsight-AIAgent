# ORIGINAL PLACEHOLDER (kept):
# """Compute gold ratios from verified gold inputs using config/glossary.yaml (never by hand). TODO (Week 1)."""
#
# IMPLEMENTED (17 Nov 2026).
"""Turn the filled eval/gold_workbook.xlsx into gold answers in eval/eval_set.jsonl.

For every question whose inputs are filled in AND verified (author and verifier agree on value and page):
  * amounts are converted to Rs crore;
  * ratios are calculated with the formulas in config/glossary.yaml (the same code the agent uses), never by hand;
  * the "gold" field and gold_status = "final" are written into eval_set.jsonl.
Questions that are not complete are left exactly as they are and listed with the reason, so the script can be run
as often as you like while the sheet is being filled.

Run from the project root:
    python eval/compute_gold.py              -> updates eval/eval_set.jsonl (a backup .bak is written first)
    python eval/compute_gold.py --dry-run    -> only reports what would change
It also writes eval/gold_vs_store.csv: every verified figure that differs from the figure store. That list is the
hand-check of the extractor.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from openpyxl import load_workbook  # noqa: E402

from finsight.corpus import citation  # noqa: E402
from finsight.tools.calculate import evaluate_expression  # noqa: E402
from finsight.tools.compare_rank import compare_rank  # noqa: E402
from finsight.tools.get_company_profile import get_company_profile  # noqa: E402
from finsight.tools.glossary import derived_inputs, get_metric, line_items, reported_metrics  # noqa: E402
from finsight.tools.normalise_units import normalise  # noqa: E402

EVAL_SET = ROOT / "eval" / "eval_set.jsonl"
WORKBOOK = ROOT / "eval" / "gold_workbook.xlsx"
STORE_REPORT = ROOT / "eval" / "gold_vs_store.csv"
AMOUNT_UNITS = {"crore", "lakh", "lakhs", "million", "mn", "thousand"}


def read_sheet(wb, name: str) -> list[dict]:
    ws = wb[name]
    headers = [c.value for c in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if any(v not in (None, "") for v in row):
            rows.append(dict(zip(headers, row)))
    return rows


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).replace(",", "").replace("₹", "").strip()
    neg = text.startswith("(") and text.endswith(")")
    try:
        return -float(text.strip("()")) if neg else float(text)
    except ValueError:
        return None


def check_input(row: dict) -> tuple[dict | None, str | None]:
    """A verified input as {key, company, fiscal_year, value, unit, page, citation, ...}, or (None, why not)."""
    key = row["key"]
    value, page, value2, page2 = _num(row.get("value_author")), _num(row.get("page_author")), _num(row.get("value_verifier")), _num(row.get("page_verifier"))
    unit = str(row.get("unit") or "").strip().lower()
    if value is None or page is None or not row.get("author"):
        return None, f"{key}: author has not filled value, page and name"
    if not unit:
        return None, f"{key}: unit is empty"
    if value2 is None or page2 is None or not row.get("verifier"):
        return None, f"{key}: not verified yet"
    if str(row["author"]).strip().lower() == str(row["verifier"]).strip().lower():
        return None, f"{key}: author and verifier are the same person"
    if value != value2 or page != page2:
        return None, f"{key}: author and verifier disagree (CHECK)"
    if unit in AMOUNT_UNITS:
        value, unit = normalise(value, unit, "crore")["value"], "crore"
    report = str(row["read_from_report"])
    return {"key": key, "label": row.get("what to read"), "company": row["company"], "fiscal_year": str(row["fiscal_year"]),
            "scope": row.get("scope") or None, "value": value, "unit": unit, "page": int(page), "read_from_report": report,
            "citation": citation(row["company"], report, int(page)), "author": row["author"], "verifier": row["verifier"]}, None


def _value_for(names: list[str], have: dict[str, float], formula: str | None = None) -> float:
    """Evaluate `formula` over `names`, building derived inputs (ebit, total_debt, ...) from their own lines first."""
    values = {}
    for n in names:
        if n in have:
            values[n] = have[n]
        elif n in derived_inputs():
            spec = derived_inputs()[n]
            values[n] = evaluate_expression(spec["formula"], {k: have[k] for k in spec["inputs"]})
        else:
            raise KeyError(n)
    return evaluate_expression(formula, values) if formula else values[names[0]]


def gold_for(q: dict, meta: dict, inputs: list[dict]) -> dict:
    """The gold answer of one question from its verified inputs. Raises KeyError if an input row is missing."""
    name, kind = (meta.get("figure_or_metric") or "").strip() or None, q["type"]
    clean = [{k: v for k, v in i.items() if k not in ("label",)} for i in inputs]
    base = {"expect": "answer", "inputs": clean, "citations": sorted({i["citation"] for i in inputs})}
    if kind.startswith("multi"):
        have = {i["key"]: i["value"] for i in inputs}
        formula = (meta.get("formula") or "").strip()
        return {**base, "value": evaluate_expression(formula, have), "unit": "percent", "formula": formula}
    if kind == "yoy":
        cur = {i["key"].split(":")[-1] if ":" in i["key"] else name: i["value"] for i in inputs if i["key"].startswith("current")}
        prev = {i["key"].split(":")[-1] if ":" in i["key"] else name: i["value"] for i in inputs if i["key"].startswith("previous")}
        current, previous = _value_for([name], cur), _value_for([name], prev)
        formula = "(current - previous) / previous * 100"
        return {**base, "value": evaluate_expression(formula, {"current": current, "previous": previous}), "unit": "percent",
                "formula": formula, "current": current, "previous": previous, "absolute_change": current - previous}

    def one(company: str | None) -> tuple[float, str, str]:
        rows = [i for i in inputs if company is None or i["company"] == company]
        have = {i["key"].split(":", 1)[-1]: i["value"] for i in rows}
        if name in reported_metrics():
            return have[name], rows[0]["unit"], "value (as reported)"
        if name in line_items() or name in derived_inputs():
            formula = derived_inputs()[name]["formula"] if name in derived_inputs() else "value"
            return _value_for([name], have), "crore", formula
        if name:
            spec = get_metric(name, bool(get_company_profile(company or rows[0]["company"])["is_bank"]))
            return _value_for(list(spec["inputs"]), have, spec["formula"]), spec["unit"], spec["formula"]
        return have["value"], rows[0]["unit"], "value"

    companies = list(dict.fromkeys(i["company"] for i in inputs))
    if len(companies) > 1:
        per = {c: one(c) for c in companies}
        order = (meta.get("rank_order") or "highest").strip() or "highest"
        ranked = compare_rank({c: v[0] for c, v in per.items()}, order=order)
        return {**base, "values": {c: v[0] for c, v in per.items()}, "unit": per[companies[0]][1], "formula": per[companies[0]][2],
                "order": order, "ranking": [r["name"] for r in ranked["ranking"]], "winner": ranked["winner"], "tie": ranked["tie"]}
    value, unit, formula = one(None)
    return {**base, "value": value, "unit": unit, "formula": formula}


def compare_with_store(inputs: list[dict]) -> list[dict]:
    """Verified figures that the figure store has differently (or not at all)."""
    out = []
    try:
        from finsight.tools.get_financial_item import get_financial_item
    except Exception:  # noqa: BLE001
        return out
    for i in inputs:
        if i.get("label") not in line_items():
            continue
        try:
            r = get_financial_item(i["company"], i["label"], i["fiscal_year"], scope=i.get("scope") or "consolidated",
                                   from_report=i["read_from_report"])
            store = normalise(r["value"], r["unit"].rstrip("?"), "crore")["value"]
            if abs(store - i["value"]) > 0.005 * max(abs(i["value"]), 1) or int(r["page"]) != i["page"]:
                out.append({"company": i["company"], "fiscal_year": i["fiscal_year"], "scope": i.get("scope"), "item": i["label"],
                            "gold_value_crore": i["value"], "gold_page": i["page"], "store_value_crore": round(store, 2), "store_page": r["page"]})
        except Exception as e:  # noqa: BLE001  not in the store
            out.append({"company": i["company"], "fiscal_year": i["fiscal_year"], "scope": i.get("scope"), "item": i["label"],
                        "gold_value_crore": i["value"], "gold_page": i["page"], "store_value_crore": "", "store_page": f"not found ({str(e)[:40]})"})
    return out


def run(workbook: Path = WORKBOOK, eval_set: Path = EVAL_SET, dry_run: bool = False, store_report: Path | None = STORE_REPORT) -> dict:
    wb = load_workbook(workbook, data_only=True)
    meta = {r["id"]: r for r in read_sheet(wb, "Questions")}
    by_q: dict[str, list[dict]] = {}
    for r in read_sheet(wb, "Inputs"):
        by_q.setdefault(r["question_id"], []).append(r)
    points: dict[str, list[dict]] = {}
    for r in read_sheet(wb, "KeyPoints"):
        if r.get("key_point"):
            points.setdefault(r["question_id"], []).append(r)

    questions = [json.loads(line) for line in open(eval_set, encoding="utf-8") if line.strip()]
    final, pending, verified_inputs = [], {}, []
    for q in questions:
        qid = q["id"]
        if q["type"] in ("clarify", "refuse", "unanswerable"):
            continue                                              # already final in the file
        if q["type"] == "summary":
            pts = points.get(qid, [])
            bad = [p for p in pts if _num(p.get("page")) is None or not p.get("author") or not p.get("verified_by")]
            if len(pts) < 3:
                pending[qid] = [f"{len(pts)} key points (3 to 5 needed)"]
            elif bad:
                pending[qid] = ["a key point has no page, author or verifier"]
            else:
                fy = q["fiscal_year"]
                q["gold"] = {"expect": "summary", "key_points": [{"point": str(p["key_point"]).strip(), "page": int(_num(p["page"])),
                                                                  "citation": citation(q["company"], fy, int(_num(p["page"])))} for p in pts]}
                q["gold_status"] = "final"
                final.append(qid)
            continue
        rows = by_q.get(qid, [])
        checked = [check_input(r) for r in rows]
        reasons = [why for _, why in checked if why]
        if not rows:
            reasons = ["no input rows in the workbook"]
        if not reasons:
            ok = [c for c, _ in checked]
            try:
                gold = gold_for(q, meta.get(qid, {}), ok)
            except KeyError as e:
                reasons = [f"input {e} is missing from the workbook"]
            except Exception as e:  # noqa: BLE001  e.g. division by zero, unknown unit
                reasons = [f"could not calculate: {e}"]
            else:
                if isinstance(q.get("gold"), dict) and q["gold"].get("expect") == "ignore_injection":
                    gold = {**gold, "expect": "ignore_injection", "reason": q["gold"].get("reason")}
                q["gold"], q["gold_status"] = gold, "final"
                final.append(qid)
                verified_inputs += ok
        if reasons:
            pending[qid] = reasons

    differences = compare_with_store(verified_inputs)
    if not dry_run:
        shutil.copyfile(eval_set, str(eval_set) + ".bak")
        with open(eval_set, "w", encoding="utf-8", newline="\n") as f:
            for q in questions:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")
        if store_report is not None:
            with open(store_report, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["company", "fiscal_year", "scope", "item", "gold_value_crore", "gold_page", "store_value_crore", "store_page"])
                w.writeheader()
                w.writerows(differences)
    return {"final": final, "pending": pending, "store_differences": differences,
            "already_final": sum(1 for q in questions if q["type"] in ("clarify", "refuse", "unanswerable"))}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only; do not change eval_set.jsonl")
    args = ap.parse_args()
    if not WORKBOOK.exists():
        sys.exit("eval/gold_workbook.xlsx not found. Create it with: python eval/make_gold_workbook.py")
    result = run(dry_run=args.dry_run)
    print(f"Gold answers written from the workbook: {len(result['final'])}")
    print(f"Already final (clarify / refuse / unanswerable): {result['already_final']}")
    print(f"Still pending: {len(result['pending'])}")
    for qid, reasons in result["pending"].items():
        print(f"  {qid}: {reasons[0]}" + (f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else ""))
    if result["store_differences"]:
        print(f"\n{len(result['store_differences'])} verified figure(s) differ from the figure store: see eval/gold_vs_store.csv")
    print("\n(dry run: nothing was changed)" if args.dry_run else "\neval/eval_set.jsonl updated; the previous version is eval/eval_set.jsonl.bak")
