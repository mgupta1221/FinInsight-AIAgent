# ORIGINAL PLACEHOLDER (kept):
# """Run the full agent (and a single_rag ablation) over eval_set.jsonl; save runs to results/runs/. TODO (Week 2)."""
# if __name__ == "__main__":
#     print("TODO: run evaluation over eval/eval_set.jsonl")
#
# IMPLEMENTED (21 Nov 2026).
"""Ask every question of eval/eval_set.jsonl, save the answers, score them and print the results table.

    python eval/run_eval.py                      practice run of the agent      -> results/runs/<time>_agent/
    python eval/run_eval.py --mode simple        practice run of simple search  -> results/runs/<time>_simple/
    python eval/run_eval.py --mode closed_book   the model WITHOUT the reports; also few_shot, cot_sc, decompose
                                                 (added 22 Nov 2026, see eval/baselines.py)
    python eval/run_eval.py --official           OFFICIAL run (all questions)   -> results/official/<time>_agent/
    python eval/run_eval.py --limit 10           the first 10 questions only
    python eval/run_eval.py --types summary,refuse      only these question types
    python eval/run_eval.py --ids ratio-008,yoy-012     only these questions
    python eval/run_eval.py --resume results/runs/<folder>     continue a run that was interrupted

WHY two folders: practice runs are made while the agent is still being fixed. They stay on the laptop
(results/runs/ is in .gitignore) and can be deleted at any time. An official run is made on frozen code, always
with all questions, and its folder is committed. Nothing lands in results/official/ unless --official is typed.

Each question is asked in a conversation of its own, so no question can borrow a company or a year from the one
before it. "agent" is the full agent (finsight.agent.graph.run), the same one the chat screen uses. "simple" is
the Week-1 path (retrieve passages, let the model answer), kept as the comparison the report needs.

Files written to the run folder:
    answers.jsonl   one line per question: status, value, unit, scope, ranking, key points, citations, steps, tokens, seconds
    traces.jsonl    the step-by-step record of each answer (personal data masked)
    scored.csv      one row per question: right or wrong, why, expected, got          (open in Excel)
    summary_review.csv   each gold key point beside the agent's summary; type Y or N in `human_covered`,
                         then: python eval/run_eval.py --rescore <folder>
    errors.csv      the wrong answers with a failure label                             (open in Excel)
    metrics.json, summary.txt, run_info.json
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "eval")]

# NEW (21 Nov 2026): the same quiet settings as scripts/ask.py.
# WHY: after the 15th question of the first run, lines such as "Could not reach the Hub ... offline mode is
#      enabled" and "Loading weights: 100%" appeared between the progress lines. They are harmless: the first
#      question that needs a text search loads the two search models from the laptop's cache. Hidden here.
import os  # noqa: E402
for _k, _v in (("TQDM_DISABLE", "1"), ("HF_HUB_DISABLE_PROGRESS_BARS", "1"), ("HF_HUB_DISABLE_SYMLINKS_WARNING", "1"),
               ("TRANSFORMERS_VERBOSITY", "error"), ("HF_HUB_VERBOSITY", "error"), ("TOKENIZERS_PARALLELISM", "false")):
    os.environ.setdefault(_k, _v)
import logging  # noqa: E402
for _n in ("huggingface_hub", "sentence_transformers", "transformers"):
    logging.getLogger(_n).setLevel(logging.ERROR)

import metrics    # noqa: E402
import score      # noqa: E402
import taxonomy   # noqa: E402

EVAL_SET = ROOT / "eval" / "eval_set.jsonl"
PRACTICE, OFFICIAL = ROOT / "results" / "runs", ROOT / "results" / "official"


def ask_agent(question: str, qid: str) -> tuple[dict, list]:
    """One question through the full agent, in a fresh conversation. Returns (answer record, trace)."""
    from finsight.agent.graph import run
    from finsight.agent.memory import Memory
    from finsight.config import settings
    a = run(question, session_id=f"eval-{qid}", memory=Memory(":memory:"))
    steps = sum(1 for t in a.trace if "step" in t)
    rec = {"status": a.status, "answer": a.answer or a.clarifying_question or "", "value": a.value, "unit": a.unit, "scope": a.scope,
           "metric": a.metric, "formula": a.formula, "companies": a.companies, "fiscal_years": a.fiscal_years, "ranking": a.ranking,
           "answer_company": a.answer_company, "key_points": [k.model_dump() for k in a.key_points], "citations": a.citations,
           "inputs": [f.model_dump() for f in a.inputs], "caveats": a.caveats, "verified": a.verified,
           "refusal_reason": a.refusal_reason, "steps": steps, "tokens": a.tokens_used,
           "within_limits": steps <= settings.max_steps and a.tokens_used <= settings.token_budget}
    return rec, a.trace


def ask_simple(question: str, qid: str) -> tuple[dict, list]:
    """One question through the Week-1 path: search once, let the model answer from the passages."""
    from finsight.qa import answer_question
    r = answer_question(question, top_k=5)
    cites = [p["citation"] for p in r.get("passages", [])]
    rec = {"status": "answered", "answer": r["answer"], "value": None, "unit": None, "scope": None, "citations": cites,
           "key_points": [], "ranking": [], "steps": 1, "tokens": 0, "within_limits": True}
    return rec, [{"tool": "search_report", "result": cites}]


# NEW (22 Nov 2026): is the vector search usable?
# WHY: a practice run was made while Qdrant was not running. The search then falls back to keyword search only
#      and prints one warning per search between the progress lines. Nothing stops, but summaries and ratios read
#      from report text get worse passages: that run scored 2 of 8 on summaries where the runs before had 4 of 8,
#      and the cause was easy to miss. The evaluation now checks once, before the first question. A practice run
#      goes on with a clear warning and the fact is written to run_info.json; an OFFICIAL run does not start.
def search_ready() -> tuple[bool, str]:
    """(True, "") if the vector index answers and holds passages; else (False, why)."""
    try:
        from finsight.tools.search_report import _get_store
        n = _get_store().count()
        return (True, "") if n else (False, "the search index is empty; run the ingest")
    except Exception as e:  # noqa: BLE001  connection refused, collection missing ...
        return False, str(e)[:160]


def _safe(obj, key: str | None = None):
    """A copy of a trace that can be stored: e-mail addresses and PAN-like ids are masked in every text, phone
    numbers only in the user's own question. WHY not everywhere: a figure such as 31052504740 looks like a phone
    number to the masking rule, and the trace is where the figures are checked."""
    from finsight.safety.pii import mask_pii
    if isinstance(obj, dict):
        return {k: _safe(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe(v, key) for v in obj]
    if isinstance(obj, str):
        if key == "question":
            return mask_pii(obj)
        return re.sub(r"\b[A-Z]{5}\d{4}[A-Z]\b", "[pan]", re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", obj))
    return obj


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001  git not installed, or not a clone
        return ""


def _write_csv(path: Path, rows: list[dict]) -> None:
    if rows:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:      # utf-8-sig: Excel shows the rupee sign correctly
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


def finish(out: Path, questions: list[dict], info: dict) -> dict:
    """Score a run folder: writes scored.csv, errors.csv, metrics.json and summary.txt. Returns the metrics."""
    answers = [json.loads(line) for line in open(out / "answers.jsonl", encoding="utf-8") if line.strip()]
    # NEW (21 Nov 2026): the summary review sheet. Written once; a sheet a person has started to fill is never
    # overwritten, and its Y / N marks are used when the run is scored again (--rescore).
    sheet = out / "summary_review.csv"
    review = score.read_review(sheet) if sheet.exists() else {}
    if not sheet.exists():
        _write_csv(sheet, score.review_rows(questions, answers))
    scored = score.score_all(questions, answers, review)
    errors = taxonomy.label_all(scored, questions, answers)
    m = metrics.compute(scored)
    m["errors"] = taxonomy.counts(errors)
    _write_csv(out / "scored.csv", scored)
    _write_csv(out / "errors.csv", errors)
    if not errors and (out / "errors.csv").exists():
        (out / "errors.csv").unlink()
    (out / "metrics.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    kind = "OFFICIAL" if info.get("official") else "practice"
    text = metrics.table(m, m["errors"], title=f"{kind} run, mode {info.get('mode')}: {out.name}")
    (out / "summary.txt").write_text(text + "\n", encoding="utf-8")
    return m


def run(mode: str = "agent", official: bool = False, limit: int | None = None, ids: list[str] | None = None,
        types: list[str] | None = None, resume: Path | None = None, eval_set: Path = EVAL_SET, ask=None,
        practice_dir: Path = PRACTICE, official_dir: Path = OFFICIAL, label: str = "", quiet: bool = False,
        search_check=None) -> Path:
    questions = [json.loads(line) for line in open(eval_set, encoding="utf-8") if line.strip()]
    if official and (limit or ids or types):
        raise SystemExit("An official run always asks every question: do not combine --official with --limit, --ids or --types.")
    not_final = [q["id"] for q in questions if q.get("gold_status") != "final"]
    if official and not_final:
        raise SystemExit(f"{len(not_final)} question(s) have no final gold answer yet ({', '.join(not_final[:5])} ...). Run eval/compute_gold.py first.")
    chosen = [q for q in questions if (not ids or q["id"] in ids) and (not types or q["type"] in types)][: limit or None]
    # OLD: ask = ask or (ask_simple if mode == "simple" else ask_agent)
    # CHANGED (22 Nov 2026): four more modes, the baselines without the reports (eval/baselines.py).
    import baselines
    by_mode = {"agent": ask_agent, "simple": ask_simple, **baselines.ASK}
    given = ask
    ask = ask or by_mode[mode]

    if resume:
        out = Path(resume)
        info = json.loads((out / "run_info.json").read_text(encoding="utf-8"))
        mode, official = info["mode"], info["official"]
        # OLD: ask = ask_simple if mode == "simple" and ask is ask_agent else ask
        ask = given or by_mode[mode]                         # the mode of the run that is continued decides
    else:
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        base = (official_dir if official else practice_dir) / f"{stamp}_{mode}{'_' + label if label else ''}"
        out, n = base, 1
        while out.exists():                                   # two runs started in the same second never share a folder
            n += 1
            out = base.with_name(f"{base.name}_{n}")
        out.mkdir(parents=True)
        from finsight.config import settings
        info = {"mode": mode, "official": official, "started": dt.datetime.now().isoformat(timespec="seconds"), "model": settings.model_name,
                "commit": _commit(), "questions": len(chosen), "eval_set": str(Path(eval_set).name)}
        (out / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    # NEW (22 Nov 2026): see search_ready() above. Only the modes that search the reports are checked, and not a
    # run whose answers come from a function given by a test.
    if mode in ("agent", "simple") and (given is None or search_check is not None):
        ok, why = (search_check or search_ready)()
        info["vector_search"] = ok
        (out / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        if not ok:
            msg = (f"Vector search is NOT available ({why}).\n"
                   "Start Qdrant first (Docker Desktop running, then: docker compose --env-file .env up -d qdrant), "
                   "or check QDRANT_URL in .env.")
            if official:
                raise SystemExit("An official run needs the vector search.\n" + msg)
            if not quiet:
                print("\n" + "!" * 78 + "\nWARNING: " + msg + "\nThis practice run goes on with keyword search only. "
                      "Summaries and ratios read from report text will score lower.\n" + "!" * 78 + "\n", flush=True)
    done = {json.loads(line)["id"] for line in open(out / "answers.jsonl", encoding="utf-8")} if (out / "answers.jsonl").exists() else set()

    todo = [q for q in chosen if q["id"] not in done]
    with open(out / "answers.jsonl", "a", encoding="utf-8") as fa, open(out / "traces.jsonl", "a", encoding="utf-8") as ft:
        for n, q in enumerate(todo, 1):
            t0 = time.perf_counter()
            try:
                rec, trace = ask(q["question"], q["id"])
            except Exception as e:  # noqa: BLE001  endpoint down, search down ... : recorded, the run goes on
                rec, trace = {"status": "error", "answer": f"{type(e).__name__}: {e}"[:300], "citations": [], "steps": 0, "tokens": 0,
                              "within_limits": True}, []
            rec = {"id": q["id"], "type": q["type"], "mode": mode, "question": q["question"], **rec, "seconds": round(time.perf_counter() - t0, 2)}
            fa.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            fa.flush()
            ft.write(json.dumps({"id": q["id"], "trace": _safe(trace)}, ensure_ascii=False, default=str) + "\n")
            ft.flush()
            if not quiet:
                print(f"[{n}/{len(todo)}] {q['id']:<16}{rec['status']:<10}{rec['seconds']:>7.1f}s", flush=True)

    info["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    (out / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    finish(out, [q for q in chosen], info)
    if not quiet:
        print("\n" + (out / "summary.txt").read_text(encoding="utf-8"))
        print(f"Files: {out}")
        print("Open scored.csv in Excel to see every question; errors.csv lists the wrong ones.")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run the evaluation set through the agent (or simple search) and score it.")
    # OLD: ap.add_argument("--mode", choices=["agent", "simple"], default="agent")
    ap.add_argument("--mode", choices=["agent", "simple", "closed_book", "few_shot", "cot_sc", "decompose"], default="agent",
                    help="agent; simple = search once and answer; the other four answer WITHOUT the reports (eval/baselines.py)")
    ap.add_argument("--official", action="store_true", help="save to results/official/ (all questions, frozen code)")
    ap.add_argument("--limit", type=int, help="only the first N questions (practice)")
    ap.add_argument("--ids", help="comma-separated question ids (practice)")
    ap.add_argument("--types", help="comma-separated question types (practice)")
    ap.add_argument("--resume", help="continue an interrupted run in this folder")
    ap.add_argument("--label", default="", help="a short word added to the folder name")
    ap.add_argument("--rescore", help="score this run folder again, without asking any question (after filling summary_review.csv)")
    a = ap.parse_args()
    if not EVAL_SET.exists():
        sys.exit("eval/eval_set.jsonl not found")
    if a.rescore:
        folder = Path(a.rescore)
        info = json.loads((folder / "run_info.json").read_text(encoding="utf-8"))
        asked = {json.loads(line)["id"] for line in open(folder / "answers.jsonl", encoding="utf-8") if line.strip()}
        finish(folder, [q for q in (json.loads(line) for line in open(EVAL_SET, encoding="utf-8") if line.strip()) if q["id"] in asked], info)
        print((folder / "summary.txt").read_text(encoding="utf-8"))
        sys.exit(0)
    run(mode=a.mode, official=a.official, limit=a.limit, ids=a.ids.split(",") if a.ids else None,
        types=a.types.split(",") if a.types else None, resume=Path(a.resume) if a.resume else None, label=a.label)
