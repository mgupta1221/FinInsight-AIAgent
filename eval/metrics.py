# ORIGINAL PLACEHOLDER (kept):
# """Compute metrics: accuracy, citation rate, calc-transparency, recall@k, latency, tokens/cost. TODO (Week 2)."""
#
# IMPLEMENTED (21 Nov 2026). recall@k of the search is measured separately by eval/retrieval_experiment.py.
"""Turn a score sheet into the results table, and several runs into one average.

    python eval/metrics.py results/runs/<run folder>     -> the table of one run
    python eval/metrics.py results/official              -> average, lowest and highest over all runs in the folder

Metrics: accuracy overall and per question type; citation rate (answers that cite a page); page match (a cited
page is a gold page); calculation transparency (computed answers that show their formula); share of runs within
the step and token limits; average steps, tokens and seconds per question.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

TYPE_ORDER = ["fact", "ratio", "yoy", "compare_rank", "multi_hop_note", "summary", "clarify", "refuse", "unanswerable", "injection_doc"]


def _rate(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) not in ("", None)]
    return round(sum(1 for v in vals if v in (True, "True")) / len(vals), 4) if vals else None


def compute(scored: list[dict]) -> dict:
    ok = lambda r: r["correct"] in (True, "True")                                     # noqa: E731  (rows may come back from a CSV)
    by_type = {}
    for t in TYPE_ORDER + sorted({r["type"] for r in scored} - set(TYPE_ORDER)):
        rows = [r for r in scored if r["type"] == t]
        if rows:
            by_type[t] = {"n": len(rows), "correct": sum(map(ok, rows)), "accuracy": round(sum(map(ok, rows)) / len(rows), 4)}
    answered = [r for r in scored if r["status"] == "answered"]
    num = lambda k: round(statistics.mean(float(r[k] or 0) for r in scored), 2) if scored else 0.0   # noqa: E731
    return {"n": len(scored), "correct": sum(map(ok, scored)), "accuracy": round(sum(map(ok, scored)) / len(scored), 4) if scored else 0.0,
            "by_type": by_type, "citation_rate": _rate(answered, "cited"), "page_match_rate": _rate(answered, "page_match"),
            "calc_transparency": _rate(answered, "formula_shown"), "within_limits": _rate(scored, "within_limits"),
            "avg_steps": num("steps"), "avg_tokens": num("tokens"), "avg_seconds": num("seconds"),
            "status": {s: sum(1 for r in scored if r["status"] == s) for s in sorted({str(r["status"]) for r in scored})}}


def _pct(v) -> str:
    return "   n/a" if v is None else f"{v * 100:5.1f}%"


def table(m: dict, errors: dict[str, int] | None = None, title: str = "") -> str:
    lines = [title or "Results", "=" * max(len(title), 7), f"{'Question type':<18}{'n':>4}{'correct':>9}{'accuracy':>10}"]
    for t, v in m["by_type"].items():
        lines.append(f"{t:<18}{v['n']:>4}{v['correct']:>9}{_pct(v['accuracy']):>10}")
    lines += [f"{'ALL':<18}{m['n']:>4}{m['correct']:>9}{_pct(m['accuracy']):>10}", "",
              f"Answers that cite a page:           {_pct(m['citation_rate'])}",
              f"A cited page is a gold page:        {_pct(m['page_match_rate'])}",
              f"Computed answers showing a formula: {_pct(m['calc_transparency'])}",
              f"Within the step and token limits:   {_pct(m['within_limits'])}",
              f"Average per question: {m['avg_steps']} steps, {m['avg_tokens']:,.0f} tokens, {m['avg_seconds']} seconds",
              "Status: " + ", ".join(f"{k} {v}" for k, v in m["status"].items())]
    if errors:
        lines += ["", "Wrong answers by cause: " + ", ".join(f"{k} {v}" for k, v in errors.items())]
    return "\n".join(lines)


def read_scored(run_dir: Path) -> list[dict]:
    with open(Path(run_dir) / "scored.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def aggregate(folder: Path) -> dict:
    """Average, lowest and highest accuracy over the runs in a folder, per mode."""
    out: dict[str, dict] = {}
    for run in sorted(p for p in Path(folder).iterdir() if (p / "metrics.json").exists()):
        m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
        info = json.loads((run / "run_info.json").read_text(encoding="utf-8")) if (run / "run_info.json").exists() else {}
        out.setdefault(info.get("mode", "agent"), {"runs": [], "overall": [], "by_type": {}})
        g = out[info.get("mode", "agent")]
        g["runs"].append(run.name)
        g["overall"].append(m["accuracy"])
        for t, v in m["by_type"].items():
            g["by_type"].setdefault(t, []).append(v["accuracy"])
    return out


def aggregate_table(agg: dict) -> str:
    lines = []
    for mode, g in agg.items():
        lines += [f"Mode: {mode}  ({len(g['runs'])} run(s))", f"{'Question type':<18}{'average':>9}{'lowest':>9}{'highest':>9}"]
        for t, vals in g["by_type"].items():
            lines.append(f"{t:<18}{_pct(statistics.mean(vals)):>9}{_pct(min(vals)):>9}{_pct(max(vals)):>9}")
        lines += [f"{'ALL':<18}{_pct(statistics.mean(g['overall'])):>9}{_pct(min(g['overall'])):>9}{_pct(max(g['overall'])):>9}", ""]
    return "\n".join(lines) if lines else "No scored runs in this folder."


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/official")
    if (target / "scored.csv").exists():
        print(table(compute(read_scored(target)), title=f"Results of {target.name}"))
    elif target.exists():
        print(aggregate_table(aggregate(target)))
    else:
        sys.exit(f"{target} does not exist")
