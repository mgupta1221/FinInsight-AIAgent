"""Tests for the evaluation scripts: eval/run_eval.py, score.py, metrics.py and taxonomy.py.

NEW FILE (21 Nov 2026). No model, no network and no PDFs: the "agent" here is a small function with scripted replies.
"""
import json
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1] / "eval"
sys.path.insert(0, str(EVAL))
import metrics    # noqa: E402
import run_eval   # noqa: E402
import score      # noqa: E402
import taxonomy   # noqa: E402

G_FACT = {"expect": "answer", "value": 178650.0, "unit": "crore", "formula": "value", "citations": ["INFY-FY2526-p287"]}
G_RATIO = {"expect": "answer", "value": 16.1148, "unit": "percent", "formula": "ebit / revenue_from_operations * 100", "citations": ["WIPRO-FY2526-p284"]}
G_RANK = {"expect": "answer", "values": {"TCS": 25.0, "INFY": 20.9, "WIPRO": 16.1}, "ranking": ["TCS", "INFY", "WIPRO"], "winner": "TCS",
          "formula": "ebit / revenue_from_operations * 100", "citations": ["TCS-FY2526-p168"]}
G_SUM = {"expect": "summary", "key_points": [
    {"point": "Cyber security risk is growing with digital transformation and is managed by a security operations centre.", "page": 111, "citation": "ITC-FY2526-p111"},
    {"point": "Commodity price volatility is managed through hedging and long-term supplier contracts.", "page": 112, "citation": "ITC-FY2526-p112"},
    {"point": "Climate change exposes the company to physical and transition risks.", "page": 111, "citation": "ITC-FY2526-p111"}]}
QUESTIONS = [
    {"id": "fact-001", "type": "fact", "question": "What was Infosys' consolidated revenue from operations in FY2025-26?", "company": "INFY", "fiscal_year": "2025-26", "statement": "consolidated", "gold": G_FACT, "gold_status": "final"},
    {"id": "ratio-001", "type": "ratio", "question": "What was Wipro's operating margin in FY2025-26?", "company": "WIPRO", "fiscal_year": "2025-26", "statement": "consolidated", "gold": G_RATIO, "gold_status": "final"},
    {"id": "compare-001", "type": "compare_rank", "question": "Which of TCS, Infosys and Wipro had the highest operating margin in FY2025-26?", "fiscal_year": "2025-26", "statement": "consolidated", "gold": G_RANK, "gold_status": "final"},
    {"id": "compare-007", "type": "compare_rank", "question": "Rank TCS, Infosys and Wipro by operating margin in FY2025-26.", "fiscal_year": "2025-26", "statement": "consolidated", "gold": G_RANK, "gold_status": "final"},
    {"id": "summary-001", "type": "summary", "question": "Summarise the top risks ITC lists in its FY2025-26 report.", "company": "ITC", "fiscal_year": "2025-26", "gold": G_SUM, "gold_status": "final"},
    {"id": "refuse-001", "type": "refuse", "question": "Should I buy TCS shares?", "gold": {"expect": "refuse", "reason": "investment advice"}, "gold_status": "final"},
    {"id": "clarify-001", "type": "clarify", "question": "What was the revenue?", "gold": {"expect": "clarify", "reason": "no company"}, "gold_status": "final"},
    {"id": "clarify-004", "type": "clarify", "question": "What was SBI's debt-to-equity ratio?", "gold": {"expect": "clarify_or_explain"}, "gold_status": "final"},
    {"id": "unanswerable-001", "type": "unanswerable", "question": "What was Reliance's revenue in FY2025-26?", "gold": {"expect": "not_in_corpus"}, "gold_status": "final"},
    {"id": "multihop-001", "type": "multi_hop_note", "question": "What share of Infosys' total borrowings was due within one year in FY2025-26?", "company": "INFY", "fiscal_year": "2025-26", "statement": "consolidated",
     "gold": {"expect": "not_applicable", "reason": "no borrowings", "citations": ["INFY-FY2526-p319"]}, "gold_status": "final"},
]
Q = {q["id"]: q for q in QUESTIONS}


def ans(**kw):
    base = {"mode": "agent", "status": "answered", "answer": "", "value": None, "unit": None, "scope": "consolidated", "citations": [],
            "ranking": [], "key_points": [], "steps": 2, "tokens": 1500, "seconds": 3.0, "within_limits": True, "fiscal_years": ["2025-26"]}
    return {**base, **kw}


GOOD = {
    "fact-001": ans(value=178650.0, unit="crore", citations=["INFY-FY2526-p287"]),
    "ratio-001": ans(value=16.11, unit="percent", formula="ebit / revenue_from_operations * 100", citations=["WIPRO-FY2526-p284"]),
    "compare-001": ans(ranking=["TCS", "WIPRO", "INFY"], answer_company="TCS", formula="x", citations=["TCS-FY2526-p168"]),     # winner right, order not asked
    "compare-007": ans(ranking=["TCS", "INFY", "WIPRO"], answer_company="TCS", formula="x", citations=["TCS-FY2526-p168"]),
    "summary-001": ans(answer="ITC lists three risks.", citations=["ITC-FY2526-p111", "ITC-FY2526-p112"], key_points=[
        {"point": "Cyber security risk grows with digital transformation; a security operations centre manages it.", "citation": "ITC-FY2526-p111"},
        {"point": "Commodity price volatility: hedging and long-term supplier contracts.", "citation": "ITC-FY2526-p112"},
        {"point": "Climate change brings physical and transition risks.", "citation": "ITC-FY2526-p111"}]),
    "refuse-001": ans(status="refused", answer="I can't give investment advice.", scope=None),
    "clarify-001": ans(status="clarify", answer="Which company do you mean?", scope=None),
    "clarify-004": ans(status="clarify", answer="Debt to equity is not a meaningful measure for a bank.", scope=None),
    "unanswerable-001": ans(status="refused", answer="Reliance is not in my corpus.", scope=None),
    "multihop-001": ans(status="refused", answer="Infosys states that it has no outstanding borrowings (INFY-FY2526-p319).", citations=["INFY-FY2526-p319"]),
}


def one(qid, **kw):
    return score.score_one(Q[qid], {"id": qid, **ans(**kw)})


def test_every_kind_of_gold_answer_is_scored_right_when_the_answer_is_right():
    rows = score.score_all(QUESTIONS, [{"id": k, **v} for k, v in GOOD.items()])
    assert len(rows) == len(QUESTIONS) and all(r["correct"] for r in rows), [(r["id"], r["reason"]) for r in rows if not r["correct"]]
    by = {r["id"]: r for r in rows}
    assert by["summary-001"]["recall"] == 1.0 and by["summary-001"]["human_review"]
    assert by["fact-001"]["page_match"] is True and by["ratio-001"]["formula_shown"] is True and by["fact-001"]["formula_shown"] == ""


def test_numbers_follow_the_half_percent_rule():
    assert one("fact-001", value=178650 * 1.004)["correct"] and not one("fact-001", value=178650 * 1.006)["correct"]
    assert one("ratio-001", value=16.12)["correct"] and not one("ratio-001", value=16.3)["correct"]      # 16.11 and 16.12 are one answer
    assert not one("fact-001", status="escalated", answer="no figure for 'revenue_from_operations'")["correct"]
    assert not one("fact-001", status="clarify", answer="Which fiscal year?")["correct"]


def test_ranking_winner_and_refusals():
    assert not one("compare-007", ranking=["TCS", "WIPRO", "INFY"])["correct"]               # "Rank ..." needs the whole order
    assert not one("compare-001", ranking=["INFY", "TCS", "WIPRO"])["correct"]               # wrong winner
    assert not one("refuse-001", value=3500.0, answer="TCS trades at ...")["correct"]
    assert not one("clarify-001", value=1000.0, answer="Revenue was 1,000 crore.")["correct"]
    assert one("clarify-004", status="refused", answer="Not meaningful for a bank.")["correct"]   # "or explain"
    assert not one("multihop-001", value=42.0, answer="42% of borrowings were due within one year.")["correct"]
    assert not one("summary-001", answer="ITC has risks.", key_points=[{"point": "Something about dividends.", "citation": "ITC-FY2526-p9"}])["correct"]


def test_simple_mode_answers_are_read_from_the_text():
    s = lambda qid, text: score.score_one(Q[qid], {"id": qid, **ans(mode="simple", answer=text)})   # noqa: E731
    assert s("fact-001", "Revenue from operations was ₹1,78,650 crore in FY2025-26 [INFY-FY2526-p287].")["correct"]
    assert s("fact-001", "Revenue from operations was ₹1,786,500 million.")["correct"]            # the report's own unit
    assert not s("fact-001", "Revenue from operations was ₹1,62,990 crore.")["correct"]
    assert s("ratio-001", "The operating margin works out to 16.1%.")["correct"]
    assert s("compare-001", "TCS had the highest margin, ahead of Infosys and Wipro.")["correct"]
    assert not s("compare-001", "Infosys leads, followed by TCS.")["correct"]
    assert s("refuse-001", "I cannot provide investment advice.")["correct"] and not s("refuse-001", "Yes, TCS looks attractive.")["correct"]
    assert s("clarify-001", "Which company do you mean?")["correct"]


def test_failure_labels():
    def lab(qid, **kw):
        a = {"id": qid, **ans(**kw)}
        return taxonomy.label(score.score_one(Q[qid], a), Q[qid], a)[0]
    assert lab("refuse-001", value=1.0, answer="Buy.") == "control"
    assert lab("fact-001", status="clarify", answer="Which year?") == "control"
    assert lab("fact-001", status="escalated", answer="I could not complete this reliably: no figure for 'x'.") == "retrieval_miss"
    assert lab("fact-001", status="escalated", answer="I stopped because the token budget for one question was used up.") == "tool_call_error"
    assert lab("fact-001", status="error", answer="ConnectionError") == "tool_call_error"
    assert lab("fact-001", value=1786500.0, citations=["INFY-FY2526-p287"]) == "unit_error"         # million read as crore
    assert lab("fact-001", value=150000.0, scope="standalone", citations=["INFY-FY2526-p209"]) == "wrong_period_or_statement"
    assert lab("fact-001", value=150000.0, citations=["INFY-FY2526-p300"]) == "wrong_item"
    assert lab("fact-001", value=150000.0, citations=["INFY-FY2526-p287"]) == "calc_error"
    assert lab("compare-007", ranking=["INFY", "TCS", "WIPRO"]) == "calc_error"
    assert lab("summary-001", answer="x") == "retrieval_miss"
    assert lab("fact-001", mode="simple", answer="Revenue was 99,999 crore.") == "hallucination"


def _fake_agent(replies):
    asked = []

    def ask(question, qid):
        asked.append(qid)
        if qid == "ratio-001" and replies.get("boom"):
            raise RuntimeError("endpoint down")
        r = dict(replies.get(qid, GOOD[qid]))
        return {k: v for k, v in r.items() if k not in ("mode", "seconds")}, [{"step": 1, "note": "contact me at someone@example.com"}]
    return ask, asked


@pytest.fixture
def evalset(tmp_path):
    p = tmp_path / "eval_set.jsonl"
    p.write_text("\n".join(json.dumps(q) for q in QUESTIONS) + "\n", encoding="utf-8")
    return p


def test_a_run_writes_its_files_scores_itself_and_keeps_practice_and_official_apart(tmp_path, evalset):
    ask, asked = _fake_agent({"fact-001": ans(value=150000.0, unit="crore", citations=["INFY-FY2526-p300"]), "boom": True})
    kw = dict(eval_set=evalset, ask=ask, practice_dir=tmp_path / "runs", official_dir=tmp_path / "official", quiet=True)
    out = run_eval.run(**kw)
    assert out.parent.name == "runs" and out.name.endswith("_agent") and not (tmp_path / "official").exists()
    for name in ("answers.jsonl", "traces.jsonl", "scored.csv", "errors.csv", "metrics.json", "summary.txt", "run_info.json"):
        assert (out / name).exists(), name
    m = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert m["n"] == 10 and m["correct"] == 8 and m["by_type"]["fact"]["accuracy"] == 0.0 and m["by_type"]["clarify"]["n"] == 2
    assert m["errors"] == {"tool_call_error": 1, "wrong_item": 1} and m["status"]["error"] == 1      # the failed question did not stop the run
    assert "someone@example.com" not in (out / "traces.jsonl").read_text(encoding="utf-8")          # personal data masked
    text = (out / "summary.txt").read_text(encoding="utf-8")
    assert "practice run" in text and "ALL" in text and "80.0%" in text
    assert metrics.compute(metrics.read_scored(out))["correct"] == 8                               # the table can be rebuilt from the CSV

    official = run_eval.run(official=True, **{**kw, "ask": _fake_agent({})[0]})
    assert official.parent.name == "official" and "OFFICIAL" in (official / "summary.txt").read_text(encoding="utf-8")
    assert json.loads((official / "metrics.json").read_text(encoding="utf-8"))["accuracy"] == 1.0
    assert "agent" in metrics.aggregate(tmp_path / "official") and "100.0%" in metrics.aggregate_table(metrics.aggregate(tmp_path / "official"))


def test_official_run_needs_everything_and_a_run_can_be_resumed_or_narrowed(tmp_path, evalset):
    ask, asked = _fake_agent({})
    kw = dict(eval_set=evalset, ask=ask, practice_dir=tmp_path / "runs", official_dir=tmp_path / "official", quiet=True)
    with pytest.raises(SystemExit):
        run_eval.run(official=True, limit=3, **kw)
    out = run_eval.run(limit=3, **kw)
    assert asked == ["fact-001", "ratio-001", "compare-001"]
    run_eval.run(resume=out, **kw)                                                                # the other seven; none asked twice
    assert len(asked) == 10 and len(set(asked)) == 10
    assert json.loads((out / "metrics.json").read_text(encoding="utf-8"))["n"] == 10
    del asked[:]
    run_eval.run(types=["refuse", "clarify"], **kw)
    assert asked == ["refuse-001", "clarify-001", "clarify-004"]
    pending = [dict(q, gold_status="pending_verification") if q["id"] == "fact-001" else q for q in QUESTIONS]
    evalset.write_text("\n".join(json.dumps(q) for q in pending) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        run_eval.run(official=True, **kw)                                                          # no official run before the gold answers are final


# ---- added 21 Nov 2026: a person's judgement of the summaries ----

def test_summary_review_sheet_and_rescore(tmp_path, evalset):
    para = ans(answer="ITC describes its risks.", citations=["ITC-FY2526-p111"], key_points=[
        {"point": "Attacks on information systems are handled by a round-the-clock monitoring team.", "citation": "ITC-FY2526-p111"},
        {"point": "Input costs swing with markets; the firm fixes prices ahead with its vendors.", "citation": "ITC-FY2526-p112"},
        {"point": "Hotter weather and floods threaten farms that supply the raw materials.", "citation": "ITC-FY2526-p111"}])
    ask, _ = _fake_agent({"summary-001": para})                                   # the right items in other words
    kw = dict(eval_set=evalset, ask=ask, practice_dir=tmp_path / "runs", official_dir=tmp_path / "official", quiet=True)
    out = run_eval.run(types=["summary"], **kw)
    rows = list(__import__("csv").DictReader(open(out / "summary_review.csv", encoding="utf-8-sig")))
    assert len(rows) == 3 and rows[0]["agent_summary"].startswith("- Attacks on information systems") and rows[0]["human_covered"] == ""
    assert json.loads((out / "metrics.json").read_text(encoding="utf-8"))["correct"] == 0          # the word count sees nothing in common

    text = (out / "summary_review.csv").read_text(encoding="utf-8-sig").splitlines()
    text = [text[0]] + [line.replace(",N,,", ",N,Y,", 1) for line in text[1:]]     # a person marks the three points as covered
    (out / "summary_review.csv").write_text("\n".join(text) + "\n", encoding="utf-8-sig")
    m = run_eval.finish(out, [Q["summary-001"]], {"mode": "agent", "official": False})
    assert m["correct"] == 1
    row = metrics.read_scored(out)[0]
    assert row["human_review"] == "done" and "judged by a person" in row["got"]
    assert "Y" in (out / "summary_review.csv").read_text(encoding="utf-8-sig")     # the filled sheet was not overwritten
    assert score.read_review(out / "summary_review.csv") == {("summary-001", 1): True, ("summary-001", 2): True, ("summary-001", 3): True}


# ---- added 22 Nov 2026: the four baselines without the reports (eval/baselines.py) ----
def test_baselines_ask_the_model_without_reports_and_keep_only_the_final_answer():
    import baselines
    calls = []

    def chat(messages, max_tokens=None, temperature=0.0):
        calls.append((messages[0]["content"][:40], temperature))
        system = messages[0]["content"]
        if system.startswith("Split"):
            return "1. Revenue in FY2024-25?\n2. Revenue in FY2025-26?\n3. Percentage change?"
        if "JSON object" in system:
            return 'Here it is: {"status": "refused", "answer": "I cannot give investment advice."}'
        if "Final answer" in system:
            return "Revenue was 900 then 1000. Change = 100 / 900.\nFinal answer: Revenue rose by 11.11 percent."
        return "Revenue from operations was Rs 1,000 crore."
    rec, trace = baselines.ask_closed_book("q", "x", chat)
    assert rec["status"] == "answered" and "1,000 crore" in rec["answer"] and rec["citations"] == [] and trace[0]["style"] == "closed_book"
    rec, _ = baselines.ask_few_shot("Should I buy TCS shares?", "x", chat)
    assert rec["status"] == "refused" and rec["answer"] == "I cannot give investment advice."
    rec, trace = baselines.ask_decompose("q", "x", chat)
    assert rec["answer"] == "Revenue rose by 11.11 percent." and rec["steps"] == 2 and "900" not in rec["answer"]   # reasoning is not scored
    assert "Percentage change" in trace[0]["parts"]
    n = len(calls)
    rec, trace = baselines.ask_cot_sc("q", "x", chat, samples=3)
    assert len(calls) == n + 3 and calls[-1][1] == 0.7 and rec["steps"] == 3 and trace[0]["votes"] == 3
    assert set(baselines.ASK) == set(baselines.MODES) <= score.FREE_TEXT


def test_self_consistency_takes_the_final_answer_given_most_often():
    import baselines
    replies = iter(["...\nFinal answer: The margin was 15.2 percent.", "...\nFinal answer: The margin was 18.0 percent.",
                    "...\nFinal answer: Operating margin: 15.2 percent", "no final line, margin 15.2 percent", "Final answer: 21 percent"])
    rec, trace = baselines.ask_cot_sc("q", "x", lambda m, **k: next(replies), samples=5)
    assert rec["answer"] == "The margin was 15.2 percent." and trace[0]["votes"] == 3 and trace[0]["of"] == 5
    assert baselines.vote_key("Rs 1,234.56 crore") == baselines.vote_key("about 1,230 crore") == "1.23e+03"
    assert baselines.final_line("a\nFinal answer: x\nFinal answer: y\nmore") == "y"
    bad = baselines.ask_few_shot("q", "x", lambda m, **k: "The answer is 5 percent {not json")[0]
    assert bad["status"] == "answered" and "5 percent" in bad["answer"]                  # not valid JSON: the raw text is scored


def test_free_text_baselines_are_scored_like_simple_search():
    s = lambda qid, **kw: score.score_one(Q[qid], {"id": qid, **ans(**kw)})   # noqa: E731
    assert s("fact-001", mode="closed_book", answer="Revenue was Rs 178,650 crore.")["correct"]
    assert not s("fact-001", mode="cot_sc", answer="Revenue was Rs 150,000 crore.")["correct"]
    refuse = next(i for i, q in Q.items() if q["gold"]["expect"] == "refuse")
    clarify = next(i for i, q in Q.items() if q["gold"]["expect"] == "clarify")
    assert s(refuse, mode="few_shot", status="refused", answer="No.")["correct"]          # the stated status counts
    assert s(clarify, mode="few_shot", status="clarify", answer="Please say more.")["correct"]
    assert not s(refuse, mode="simple", answer="TCS looks strong.")["correct"]            # simple search: unchanged
    assert not s(clarify, mode="closed_book", answer="The profit was 5 crore.")["correct"]


def test_baseline_runs_and_the_two_week1_files(tmp_path, evalset):
    import csv
    import baselines
    reply = lambda m, **k: "Final answer: Revenue was Rs 178,650 crore."   # noqa: E731
    asks = {"closed_book": lambda q, i: baselines.ask_closed_book(q, i, reply), "decompose": lambda q, i: baselines.ask_decompose(q, i, reply)}
    for mode, fn in asks.items():
        out = run_eval.run(mode=mode, eval_set=evalset, ask=fn, practice_dir=tmp_path / "runs", official_dir=tmp_path / "official", quiet=True)
        assert json.loads((out / "run_info.json").read_text(encoding="utf-8"))["mode"] == mode
    n = len(QUESTIONS)
    found = baselines.latest_runs([tmp_path / "official", tmp_path / "runs"], want=n)
    assert set(found) == {"closed_book", "decompose"}
    a, b = baselines.week1_files(found, tmp_path / "results")
    rows = list(csv.DictReader(open(a, encoding="utf-8-sig", newline="")))
    total = [r for r in rows if r["question_type"] == "ALL"]
    assert [r["mode"] for r in total] == ["closed_book", "decompose"] and all(int(r["questions"]) == n for r in total)
    assert any(int(r["correct"]) > 0 for r in total) and all(int(r["correct"]) < n for r in total)
    fails = list(csv.DictReader(open(b, encoding="utf-8-sig", newline="")))
    assert fails and {"strategy", "failure", "wrong_answers", "example_id", "example_answer"} <= set(fails[0])


def test_a_free_text_answer_that_declines_names_no_winner():
    """Real run, 22 Nov 2026: "I cannot provide the operating margin for TCS, Infosys, and Wipro ..." was marked correct."""
    s = lambda text, mode="closed_book": score.score_one(Q["compare-001"], {"id": "compare-001", **ans(mode=mode, answer=text)})   # noqa: E731
    r = s("I cannot provide the operating margin for TCS, Infosys, and Wipro for FY2025-26 as the reports are not yet available.")
    assert not r["correct"] and r["got"] == "declines to answer"
    assert not s("I need the operating margin figures for TCS, Infosys, and Wipro in FY2025-26 to answer this question.", "few_shot")["correct"]
    assert not s("I could not find the operating margin of TCS in the excerpts.", "simple")["correct"]
    assert s("TCS had the highest operating margin in FY2025-26.")["correct"]
    assert s("TCS leads, followed by Infosys and Wipro. However, exact figures are not provided here.")["correct"]   # a winner is named first
    assert not s("Infosys had the highest operating margin.")["correct"]


def test_a_run_checks_the_vector_search_before_the_first_question(tmp_path, evalset, capsys):
    """Real run, 22 Nov 2026: Qdrant was not running; the run went on with keyword search and summaries dropped."""
    ask, asked = _fake_agent({})
    kw = dict(eval_set=evalset, ask=ask, practice_dir=tmp_path / "runs", official_dir=tmp_path / "official")
    down = lambda: (False, "connection refused")   # noqa: E731
    with pytest.raises(SystemExit, match="official run needs the vector search"):
        run_eval.run(official=True, search_check=down, quiet=True, **kw)
    assert not asked                                                                 # no question was asked
    out = run_eval.run(search_check=down, **kw)                                      # a practice run goes on, with a warning
    assert "Vector search is NOT available (connection refused)" in capsys.readouterr().out and len(asked) == len(QUESTIONS)
    assert json.loads((out / "run_info.json").read_text(encoding="utf-8"))["vector_search"] is False
    out = run_eval.run(search_check=lambda: (True, ""), quiet=True, **kw)
    assert json.loads((out / "run_info.json").read_text(encoding="utf-8"))["vector_search"] is True
    out = run_eval.run(mode="closed_book", search_check=down, quiet=True, **kw)      # a mode without the reports is not checked
    assert "vector_search" not in json.loads((out / "run_info.json").read_text(encoding="utf-8"))


# ---- added 22 Nov 2026: the structured-output experiment (eval/structured_output_experiment.py) ----
def test_structured_output_experiment_counts_usable_broken_and_wrong_forms(tmp_path):
    import structured_output_experiment as soe
    from finsight.schemas import AgentPlan
    good = {"intent": "fact", "companies": ["Infosys"], "fiscal_years": ["2025-26"], "scope": "consolidated", "item": "revenue_from_operations"}
    assert soe.read_form(json.dumps(good))[0] == "valid"
    assert soe.read_form("Sure! Here is the plan:\n" + json.dumps(good) + "\nAnything else?")[0] == "extra_text"
    assert soe.read_form('{"intent": "fact", "companies": ["Infosys], ')[0] == "invalid"            # broken JSON
    assert soe.read_form('{"type": "ratio_question", "company": "Wipro"}')[0] == "invalid"          # JSON, but not the form
    q = Q["fact-001"]
    assert soe.content_faults(AgentPlan.model_validate(good), q) == []
    wrong = AgentPlan.model_validate({**good, "intent": "ratio", "companies": ["Wipro"], "fiscal_years": ["2024-25"]})
    assert soe.content_faults(wrong, q) == ["intent ratio", "company", "fiscal year"]
    assert "metric net_profit_margin" in soe.content_faults(AgentPlan.model_validate({"intent": "ratio", "companies": ["Wipro"], "fiscal_years": ["2025-26"],
                                                                                    "metric": "net_profit_margin"}), {**Q["ratio-001"], "metric": "operating_margin"})
    assert '"intent"' in soe.form_text() and "one of" in soe.form_text()

    calls = {"plain": 0}

    def plain(question, again=False):                       # broken at first, fine when asked again
        calls["plain"] += 1
        return json.dumps(good) if again else "Here you go: {intent: fact"

    def refused(question, again=False):
        raise RuntimeError("Error code: 400 - response_format json_schema is not supported")
    callers = {"agent": lambda question, again=False: AgentPlan.model_validate(good), "json_schema": refused,
               "json_object": lambda question, again=False: "```json\n" + json.dumps(good) + "\n```", "plain": plain}
    rows, summary = soe.run([Q["fact-001"], Q["ratio-001"]], callers, quiet=True)
    by = {s["way"]: s for s in summary}
    assert by["agent"]["first_try"] == 2 and by["agent"]["wrong_content"] == 1                      # right for the fact, wrong for the ratio question
    assert by["agent"]["correct"] == 1 and by["agent"]["correct_percent"] == 50.0 and "CORRECT" in soe.table(summary)
    assert by["json_schema"]["questions"] == 0 and "not supported" in by["json_schema"]["note"]
    assert by["json_object"]["first_try_extra_text"] == 2
    assert by["plain"]["after_retry"] == 2 and by["plain"]["failed"] == 0 and calls["plain"] == 4
    assert len(rows) == 6 and "not supported" in soe.table(summary)
    a, b = soe.write(rows, summary, tmp_path)
    assert a.exists() and b.read_text(encoding="utf-8-sig").startswith("way,questions,first_try")
