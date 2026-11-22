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
