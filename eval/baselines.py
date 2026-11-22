"""Baselines without the reports: the model answers from what it knows, prompted in four different ways.

NEW FILE (22 Nov 2026).

WHY: the evaluation compared the agent only with "simple search" (search the reports once, let the model answer).
     The build plan also asks for the step before that: the model with NO report text, and the prompting styles
     of the brief. Together they show how much each layer adds: model alone -> better prompting -> reports ->
     agent. Nothing here is used by the agent or by the app; these are evaluation runs only.

The four styles (run with  python eval/run_eval.py --mode <name>):

    closed_book   the question and one line of instruction
    few_shot      five worked examples first, and the answer as a small JSON object
    cot_sc        "think step by step", asked SAMPLES times at temperature 0.7; the final answer given most often wins
    decompose     first call: split the question into simple questions; second call: answer them, then the final answer

Scoring: the same scorer as for simple search (eval/score.py reads the numbers out of the answer text). Only the
FINAL answer is scored, not the reasoning, so a figure that happens to appear in the reasoning cannot count.
No style can cite a page: without report text there is no page, so "a cited page is a gold page" is 0 by design.

After the runs:  python eval/baselines.py     writes results/week1_strategies.csv and results/week1_failures.csv
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "eval")]

MODES = ["closed_book", "few_shot", "cot_sc", "decompose"]
SAMPLES = 5                     # cot_sc: how many times each question is asked

RULES = ("You answer questions about the annual reports of Indian listed companies (fiscal years FY2024-25 and "
         "FY2025-26). You have no report in front of you; answer from what you know. Give amounts in Rs crore and "
         "ratios in percent. For a comparison, name the company that ranks first at the start of the answer. "
         "If the question does not say which company, year or figure is meant, ask for it. Do not give investment "
         "advice, forecasts or price targets; say that you cannot. If you do not know a figure, say that you do not know it.")

CLOSED_BOOK = RULES + " Answer in one or two sentences."

FEW_SHOT = RULES + """ Reply with one JSON object and nothing else:
{"status": "answered" | "clarify" | "refused" | "unknown", "answer": "<one sentence with the value and its unit, or the question you ask back, or why you refuse>"}

Question: What was the profit?
{"status": "clarify", "answer": "Which company and which fiscal year do you mean?"}

Question: Should I buy TCS shares?
{"status": "refused", "answer": "I cannot give investment advice."}

Question: A company's revenue from operations was Rs 2,000 crore in FY2024-25 and Rs 2,300 crore in FY2025-26. How did it change?
{"status": "answered", "answer": "Revenue from operations rose by 15.00 percent, from Rs 2,000 crore to Rs 2,300 crore."}

Question: A company's profit before interest and tax was Rs 450 crore on revenue from operations of Rs 3,000 crore. What was its operating margin?
{"status": "answered", "answer": "The operating margin was 15.00 percent."}

Question: What was the revenue of Zenith Tools Ltd in FY2025-26?
{"status": "unknown", "answer": "I do not know this figure."}"""

COT = RULES + (" Think step by step: which figures are needed, the value of each, then the calculation. "
               "End with one line that starts with 'Final answer:' and holds the answer in one sentence.")

SPLIT = ("Split the question about a company's annual report into the simple questions that must be answered first "
         "(one figure each), followed by the calculation or comparison that is needed. Write a short numbered list "
         "and nothing else. If the question is already simple, write it once.")

SOLVE = RULES + (" Below are the question and the simple questions it was split into. Answer each simple question "
                 "in one line, then end with one line that starts with 'Final answer:' and holds the answer to the "
                 "original question in one sentence.")

_FINAL = re.compile(r"final answer\s*[:\-]\s*", re.I)


def _chat():
    from finsight.llm import chat
    return chat


def _record(text: str, status: str = "answered", calls: int = 1) -> dict:
    """An answer record in the form eval/score.py expects for free-text modes."""
    return {"status": status, "answer": " ".join((text or "").split()), "value": None, "unit": None, "scope": None,
            "citations": [], "key_points": [], "ranking": [], "steps": calls, "tokens": 0, "within_limits": True}


def final_line(text: str) -> str:
    """What follows the last 'Final answer:'; the whole text if the model did not write that line."""
    parts = _FINAL.split(text or "")
    return parts[-1].strip().split("\n")[0].strip()


def ask_closed_book(question: str, qid: str, chat=None) -> tuple[dict, list]:
    chat = chat or _chat()
    text = chat([{"role": "system", "content": CLOSED_BOOK}, {"role": "user", "content": question}], max_tokens=200)
    return _record(text), [{"style": "closed_book", "reply": text}]


def ask_few_shot(question: str, qid: str, chat=None) -> tuple[dict, list]:
    chat = chat or _chat()
    text = chat([{"role": "system", "content": FEW_SHOT}, {"role": "user", "content": f"Question: {question}"}], max_tokens=200)
    status, answer = "answered", text
    m = re.search(r"\{.*\}", text or "", re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            answer = str(obj.get("answer") or "")
            said = str(obj.get("status") or "").lower()
            status = said if said in ("clarify", "refused") else "answered"       # "unknown" is an answer that is wrong
        except ValueError:
            pass                                                                    # not valid JSON: score the raw text
    return _record(answer, status), [{"style": "few_shot", "reply": text}]


def vote_key(line: str) -> str:
    """What two final answers must share to count as the same: the first number (3 significant digits), else the first words."""
    m = re.search(r"-?\d[\d,]*\.?\d*", line)
    if m:
        try:
            return f"{float(m.group(0).replace(',', '')):.3g}"
        except ValueError:
            pass
    return " ".join(line.lower().split()[:6])


def ask_cot_sc(question: str, qid: str, chat=None, samples: int = SAMPLES) -> tuple[dict, list]:
    chat = chat or _chat()
    replies = [chat([{"role": "system", "content": COT}, {"role": "user", "content": question}], max_tokens=500, temperature=0.7)
               for _ in range(samples)]
    finals = [final_line(r) for r in replies]
    winner, votes = Counter(vote_key(f) for f in finals).most_common(1)[0]
    chosen = next(f for f in finals if vote_key(f) == winner)                       # the first sample that gave the winning answer
    return _record(chosen, calls=samples), [{"style": "cot_sc", "votes": votes, "of": samples, "finals": finals, "replies": replies}]


def ask_decompose(question: str, qid: str, chat=None) -> tuple[dict, list]:
    chat = chat or _chat()
    parts = chat([{"role": "system", "content": SPLIT}, {"role": "user", "content": question}], max_tokens=200)
    text = chat([{"role": "system", "content": SOLVE},
                 {"role": "user", "content": f"Question: {question}\n\nSimple questions:\n{parts}"}], max_tokens=500)
    return _record(final_line(text), calls=2), [{"style": "decompose", "parts": parts, "reply": text}]


ASK = {"closed_book": ask_closed_book, "few_shot": ask_few_shot, "cot_sc": ask_cot_sc, "decompose": ask_decompose}


# ---- the two Week-1 result files -------------------------------------------------------------------------------
def latest_runs(folders: list[Path], want: int = 90) -> dict[str, Path]:
    """The newest complete run of each mode (all `want` questions). An official run is preferred to a practice run."""
    best: dict[str, tuple] = {}
    for rank, folder in enumerate(folders):                     # folders[0] = official, so it wins a tie on completeness
        for run in sorted(Path(folder).glob("*")) if Path(folder).exists() else []:
            info, scored = run / "run_info.json", run / "scored.csv"
            if not (info.exists() and scored.exists()):
                continue
            meta = json.loads(info.read_text(encoding="utf-8"))
            rows = list(csv.DictReader(open(scored, encoding="utf-8-sig", newline="")))
            if len(rows) != want:
                continue
            key = (-rank, run.name)
            if meta["mode"] not in best or key > best[meta["mode"]][0]:
                best[meta["mode"]] = (key, run)
    return {mode: run for mode, (_, run) in best.items()}


def week1_files(runs: dict[str, Path], out_dir: Path) -> tuple[Path, Path]:
    """results/week1_strategies.csv (accuracy per style and question type) and week1_failures.csv (typical mistakes)."""
    order = [m for m in MODES + ["simple", "agent"] if m in runs]
    names = {"closed_book": "Closed-book", "few_shot": "Few-shot JSON", "cot_sc": f"Step by step, {SAMPLES} samples, majority",
             "decompose": "Decomposition", "simple": "Simple search (reports, one answer)", "agent": "Agent"}
    strategies, failures = [], []
    for mode in order:
        run = runs[mode]
        rows = list(csv.DictReader(open(run / "scored.csv", encoding="utf-8-sig", newline="")))
        by_type: dict[str, list[bool]] = {}
        for r in rows:
            by_type.setdefault(r["type"], []).append(r["correct"] == "True")
        for qtype, marks in list(by_type.items()) + [("ALL", [r["correct"] == "True" for r in rows])]:
            strategies.append({"strategy": names[mode], "mode": mode, "question_type": qtype, "questions": len(marks),
                               "correct": sum(marks), "accuracy_percent": round(100 * sum(marks) / len(marks), 1), "run": run.name})
        errors = list(csv.DictReader(open(run / "errors.csv", encoding="utf-8-sig", newline=""))) if (run / "errors.csv").exists() else []
        causes = Counter(e.get("failure") or e.get("label") or e.get("cause") or "" for e in errors)
        for cause, n in causes.most_common():
            ex = next(e for e in errors if (e.get("failure") or e.get("label") or e.get("cause") or "") == cause)
            failures.append({"strategy": names[mode], "mode": mode, "failure": cause, "wrong_answers": n, "example_id": ex.get("id", ""),
                             "example_question": ex.get("question", ""), "example_answer": (ex.get("answer") or "")[:300], "run": run.name})
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = (out_dir / "week1_strategies.csv", out_dir / "week1_failures.csv")
    for path, data in zip(paths, (strategies, failures)):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            if data:
                w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                w.writeheader()
                w.writerows(data)
    return paths


if __name__ == "__main__":
    found = latest_runs([ROOT / "results" / "official", ROOT / "results" / "runs"])
    if not found:
        sys.exit("No complete run found in results/official/ or results/runs/. Run python eval/run_eval.py --mode closed_book first.")
    a, b = week1_files(found, ROOT / "results")
    missing = [m for m in MODES + ["simple", "agent"] if m not in found]
    print("Used:", ", ".join(f"{m} = {p.name}" for m, p in found.items()))
    if missing:
        print("No complete run yet for:", ", ".join(missing))
    print(f"Written: {a}\n         {b}")
