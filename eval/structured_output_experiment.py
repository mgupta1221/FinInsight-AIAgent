"""Experiment: how reliably does the model fill in the planner's form, depending on how the form is asked for?

NEW FILE (22 Nov 2026). An evaluation script only: nothing here is used by the agent or by the app, and the file
can be deleted without any effect on them.

WHY: the planner asks the model for a small form (intent, companies, fiscal years, scope, metric ...). A small
     model is known to break such formats more often than a large one. This script measures it: the same
     questions are put to the planner's model step in four ways, and for each way it counts how often the reply
     was usable at once, usable after asking again, or not usable at all, and how often a usable form held the
     wrong company, year or measure.

The four ways:

    agent         as the agent does it today: the `instructor` library in its default mode (the form is offered
                  to the model as a tool to call), reply validated, asked again on a fault
    json_schema   the exact shape of the form is sent to the server (response_format json_schema), which lets
                  the model produce only text that fits it ("constrained decoding")
    json_object   the server only guarantees valid JSON (response_format json_object); the fields are described
                  in the prompt
    plain         the fields are described in the prompt and nothing is enforced

A way the endpoint does not accept is reported as "not supported" and left out of the table.

Only the questions that reach the planner are used (those the guard refuses never get there). Each question is
asked on its own, without memory. "Wrong content" compares the form with the labels of the evaluation set:
question type, company, fiscal year, and the metric for ratio questions. In the agent, code corrects many of these
afterwards (planner.resolve); this script looks at the model's reply before that correction.

    python eval/structured_output_experiment.py              all questions, about 4 x 85 model calls
    python eval/structured_output_experiment.py --limit 10   the first 10, to try it

Writes results/structured_output_experiment.csv (one row per question and way) and prints the table, which is
also saved as results/structured_output_summary.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "eval")]

WAYS = ["agent", "json_schema", "json_object", "plain"]
RETRIES = 2
AGAIN = "Your previous reply could not be read as the form. Reply with the JSON object only, with exactly the fields described."


def form_text() -> str:
    """The fields of the form in words, for the ways that describe it in the prompt."""
    from finsight.schemas import AgentPlan
    props = AgentPlan.model_json_schema()["properties"]
    lines = []
    for name, spec in props.items():
        kind = spec.get("type") or "/".join(str(x.get("type") or x.get("enum") or "") for x in spec.get("anyOf", []))
        allowed = spec.get("enum") or next((x["enum"] for x in spec.get("anyOf", []) if "enum" in x), None)
        lines.append(f'- "{name}": {kind}' + (f", one of {allowed}" if allowed else "") + (f" ({spec['description']})" if spec.get("description") else ""))
    return "Reply with one JSON object and nothing else, with exactly these fields:\n" + "\n".join(lines)


def read_form(text: str):
    """(how, plan): how is "valid" (the reply is the form and nothing else), "extra_text" (a form inside other
    text), or "invalid"; plan is the validated form or None."""
    from finsight.schemas import AgentPlan
    raw = (text or "").strip()
    for how, candidate in (("valid", raw), ("extra_text", (re.search(r"\{.*\}", raw, re.S) or [None])[0])):
        if not candidate:
            continue
        try:
            return how, AgentPlan.model_validate(json.loads(candidate))
        except Exception:  # noqa: BLE001  not JSON, or not the form
            continue
    return "invalid", None


def content_faults(plan, q: dict) -> list[str]:
    """What in a usable form disagrees with the labels of the evaluation question."""
    from finsight.tools.company_match import resolve_ticker
    faults = []
    if q["type"] in ("fact", "ratio", "yoy", "compare_rank", "summary") and plan.intent != q["type"]:
        faults.append(f"intent {plan.intent}")
    wanted = [q["company"]] if q.get("company") else list(q.get("companies") or [])
    got = {resolve_ticker(c) for c in plan.companies}
    if wanted and not set(wanted) <= got:
        faults.append("company")
    if q.get("fiscal_year") and q["fiscal_year"] not in plan.fiscal_years:
        faults.append("fiscal year")
    if q["type"] == "ratio" and q.get("metric") and plan.metric != q["metric"]:
        faults.append(f"metric {plan.metric}")
    return faults


def real_callers() -> dict:
    """The four ways against the real endpoint. Each returns the reply text (or, for "agent", the form itself)."""
    from finsight import llm
    from finsight.agent.planner import system_prompt
    from finsight.config import settings
    from finsight.schemas import AgentPlan
    system = system_prompt()

    def raw(messages, **extra):
        client, _ = llm._clients()

        def call():
            return client.chat.completions.create(model=settings.model_name, messages=messages, max_tokens=300, temperature=0.0,
                                                  extra_body=llm._extra_body(), **extra)
        return llm._strip_think(llm._with_retries(call).choices[0].message.content or "")

    def agent(question, again=False):
        return llm.structured([{"role": "system", "content": system}, {"role": "user", "content": f"Q: {question}"}],
                              AgentPlan, max_tokens=300, max_retries=RETRIES if again else 0)

    def described(question, again, **extra):
        messages = [{"role": "system", "content": system + "\n\n" + form_text()}, {"role": "user", "content": f"Q: {question}"}]
        if again:
            messages.append({"role": "user", "content": AGAIN})
        return raw(messages, **extra)

    def json_schema(question, again=False):
        fmt = {"type": "json_schema", "json_schema": {"name": "AgentPlan", "schema": AgentPlan.model_json_schema()}}
        messages = [{"role": "system", "content": system}, {"role": "user", "content": f"Q: {question}"}]
        return raw(messages + ([{"role": "user", "content": AGAIN}] if again else []), response_format=fmt)

    return {"agent": agent, "json_schema": json_schema,
            "json_object": lambda q, again=False: described(q, again, response_format={"type": "json_object"}),
            "plain": lambda q, again=False: described(q, again)}


def ask_one(way: str, call, question: str) -> tuple[str, object, str]:
    """(outcome, plan, note). Outcome: first_try, first_try_extra_text, after_retry, failed."""
    from finsight.schemas import AgentPlan

    def attempt(again: bool):
        reply = call(question, again)
        if isinstance(reply, AgentPlan):                     # the "agent" way returns the validated form
            return "valid", reply
        return read_form(reply)
    try:
        how, plan = attempt(False)
    except Exception as e:  # noqa: BLE001  the library gave up, or the endpoint refused this way
        how, plan, note = "invalid", None, f"{type(e).__name__}: {e}"[:160]
    else:
        note = ""
    if plan is not None:
        return ("first_try" if how == "valid" else "first_try_extra_text"), plan, note
    for _ in range(1 if way == "agent" else RETRIES):        # the "agent" way retries inside the library
        try:
            how, plan = attempt(True)
        except Exception as e:  # noqa: BLE001
            note = f"{type(e).__name__}: {e}"[:160]
            continue
        if plan is not None:
            return "after_retry", plan, note
    return "failed", None, note


def run(questions: list[dict], callers: dict, quiet: bool = False) -> tuple[list[dict], list[dict]]:
    """Returns (one row per question and way, one summary row per way)."""
    rows, unsupported = [], {}
    for n, q in enumerate(questions, 1):
        for way in WAYS:
            if way in unsupported or way not in callers:
                continue
            outcome, plan, note = ask_one(way, callers[way], q["question"])
            if outcome == "failed" and n == 1 and re.search(r"\b(400|404|422|not support|unsupported|BadRequest|response_format)", note, re.I):
                unsupported[way] = note                       # the endpoint does not accept this way at all
                continue
            faults = content_faults(plan, q) if plan is not None else []
            rows.append({"id": q["id"], "type": q["type"], "way": way, "outcome": outcome, "content": "wrong" if faults else ("ok" if plan is not None else ""),
                         "faults": "; ".join(faults), "form": plan.model_dump_json(exclude_none=True) if plan is not None else "", "note": note})
        if not quiet:
            print(f"[{n}/{len(questions)}] {q['id']}", flush=True)
    summary = []
    for way in WAYS:
        mine = [r for r in rows if r["way"] == way]
        if way in unsupported or not mine:
            summary.append({"way": way, "questions": 0, "first_try": "", "first_try_extra_text": "", "after_retry": "", "failed": "",
                            "wrong_content": "", "note": "not supported by the endpoint: " + unsupported.get(way, "")[:120] if way in unsupported else "not run",
                            "correct": "", "correct_percent": ""})
            continue
        count = lambda k: sum(1 for r in mine if r["outcome"] == k)   # noqa: E731
        summary.append({"way": way, "questions": len(mine), "first_try": count("first_try"), "first_try_extra_text": count("first_try_extra_text"),
                        "after_retry": count("after_retry"), "failed": count("failed"),
                        "wrong_content": sum(1 for r in mine if r["content"] == "wrong"), "note": ""})
        # ADDED (22 Nov 2026): the count a reader looks for first. Correct = a usable form with nothing wrong in it.
        summary[-1]["correct"] = sum(1 for r in mine if r["outcome"] != "failed" and r["content"] == "ok")
        summary[-1]["correct_percent"] = round(100 * summary[-1]["correct"] / len(mine), 1)
    return rows, summary


def table(summary: list[dict]) -> str:
    head = f"{'Way':<13}{'questions':>10}{'first try':>11}{'+extra text':>13}{'after retry':>13}{'failed':>8}{'wrong content':>15}{'CORRECT':>9}{'%':>7}"
    lines = [head, "-" * len(head)]
    for s in summary:
        if not s["questions"]:
            lines.append(f"{s['way']:<13}{s['note']}")
        else:
            lines.append(f"{s['way']:<13}{s['questions']:>10}{s['first_try']:>11}{s['first_try_extra_text']:>13}{s['after_retry']:>13}{s['failed']:>8}{s['wrong_content']:>15}{s['correct']:>9}{s['correct_percent']:>7}")
    return "\n".join(lines)


def write(rows: list[dict], summary: list[dict], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = (out_dir / "structured_output_experiment.csv", out_dir / "structured_output_summary.csv")
    for path, data in zip(paths, (rows, summary)):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            if data:
                w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                w.writeheader()
                w.writerows(data)
    return paths


def planner_questions(eval_set: Path) -> list[dict]:
    """The evaluation questions that reach the planner (the guard refuses the others before any model call)."""
    from finsight.safety.guard_rules import check
    return [q for q in (json.loads(line) for line in open(eval_set, encoding="utf-8") if line.strip()) if check(q["question"]) is None]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compare four ways of asking the model for the planner's form.")
    ap.add_argument("--limit", type=int, help="only the first N questions")
    a = ap.parse_args()
    # ADDED (22 Nov 2026, after the first try): stop at once if this folder cannot reach the model.
    # WHY: run from a folder without .env (the GitHub clone), every call failed on the missing certificate and the
    #      table showed 0 usable replies in all four ways, which looks like a result and is not one.
    from finsight.config import settings
    if not settings.openai_api_key or not Path(settings.ca_cert_path).exists():
        sys.exit("This folder cannot reach the model: " + ("OPENAI_API_KEY is not set in .env" if not settings.openai_api_key
                 else f"certificate not found at {settings.ca_cert_path}")
                 + ".\nRun the script from the folder that has your .env (the one the app and run_eval.py are started from).")
    qs = planner_questions(ROOT / "eval" / "eval_set.jsonl")[: a.limit or None]
    all_rows, summ = run(qs, real_callers())
    asked = [r for r in all_rows]
    if asked and all(r["outcome"] == "failed" and r["note"] for r in asked) and len({r["note"] for r in asked}) == 1:
        sys.exit(f"Every call failed with the same error, so nothing was measured and no file was written:\n  {asked[0]['note']}")
    p1, p2 = write(all_rows, summ, ROOT / "results")
    print("\n" + table(summ))
    print(f"\nfirst try = the reply was the form and nothing else; +extra text = a correct form inside other text;\n"
          f"wrong content = a usable form whose intent, company, year or metric differs from the question's labels;\n"
          f"CORRECT = questions - failed - wrong content.\n\nWritten: {p1}\n         {p2}")
