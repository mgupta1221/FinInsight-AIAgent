# ORIGINAL PLACEHOLDER (kept):
# """Wires the agents into a LangGraph StateGraph with the SqliteSaver checkpointer (cross-turn
# memory) and a recursion/step cap of settings.max_steps (=10). Exposes run(question, session_id).
# TODO (Week 2)."""
#
# IMPLEMENTED (agent layer, 13 Nov 2026) as a plain Python loop with the same public function, run().
#
# WHY a plain loop for now instead of a LangGraph StateGraph:
#   * Every transition (guard -> planner -> executor -> writer -> critic -> retry or escalate) is visible
#     in one short function, which is easier to explain, trace and unit-test with a scripted model.
#   * The nodes are separate modules with the boundaries of the original plan (guard.py, planner.py,
#     executor.py, writer.py, critic.py), the state shapes are in state.py, and memory.py plays the role
#     of SqliteSaver. Moving to LangGraph later means wrapping these same functions as graph nodes; none
#     of them has to change. The mentor's proposal allows a hand-rolled loop if the report says why.
"""The agent loop: guard -> planner -> executor -> writer -> critic, with memory, caps and escalation.

    from finsight.agent.graph import run
    answer = run("What was Infosys' consolidated revenue from operations in FY2025-26?", session_id="demo")
    print(answer.status, answer.answer, answer.citations)

Statuses: answered (critic passed) | clarify (a slot is missing) | refused (policy / out of corpus) |
escalated (could not finish reliably; names the pages to check and never guesses).
"""
from __future__ import annotations

from finsight.agent import critic, planner, writer
from finsight.agent.executor import Escalate, NotApplicable, Run   # NotApplicable: 19 Nov 2026
from finsight.agent.guard import guard
from finsight.agent.memory import Memory
from finsight.config import settings
from finsight.safety.pii import mask_pii
from finsight.safety.sanitiser import clean_question
from finsight.schemas import AgentAnswer
from finsight.tools.base import ToolError

MAX_REWRITES = 2
from finsight.corpus import fy_label, years_in  # noqa: E402   (17 Nov 2026: for the "taken from the previous question" note)
from finsight.tools.company_match import find_companies  # noqa: E402


def run(question: str, session_id: str = "default", llm=None, memory: Memory | None = None,
        use_model_wording: bool = True) -> AgentAnswer:
    if llm is None:
        from finsight.agent.llm_adapter import RealLLM
        llm = RealLLM()
    memory = memory or Memory()
    question = clean_question(question)
    trace: list[dict] = []

    def done(a: AgentAnswer) -> AgentAnswer:
        a.trace, a.tokens_used = trace, llm.tokens
        memory.log_turn(session_id, mask_pii(question), a.status, a.answer or a.clarifying_question or "")
        return a

    def over_budget() -> bool:
        return llm.tokens > settings.token_budget

    # NEW (17 Nov 2026): was the previous turn a clarifying question? Then this message may be the reply to it.
    # The unfinished question is read AND forgotten here, so it can affect this one turn only (memory.py has
    # the reason for keeping it).
    pending = memory.pop_pending(session_id)

    # 1. guard (code only, no tokens)
    refused = guard(question, trace)
    if refused:
        # NEW (18 Nov 2026): a year outside the corpus typed as the REPLY to my clarifying question does not
        # cancel that question (see the same rule in the planner block below). Advice, forecasts and the other
        # refusals still cancel it.
        if pending and refused.refusal_reason == "not_in_corpus" and planner.is_reply(question):
            memory.set_pending(session_id, pending)
            trace.append({"node": "guard", "note": "reply not usable; still waiting for an answer to my question"})
            refused.answer = f"{refused.answer} Please give it again."
        return done(refused)

    # 2. planner (model fills slots; code validates them)
    # OLD: slots = memory.get(session_id)
    slots = {k: v for k, v in memory.get(session_id).items() if not k.startswith("_")}      # "_pending" is not a slot
    # NEW (17 Nov 2026): complete the unfinished question with the reply, and plan THAT text. A message that
    # reads like a new question of its own is left alone and the unfinished one is simply dropped.
    asked = question
    if pending and planner.is_reply(question):
        asked = planner.merge_reply(pending, question)
        trace.append({"node": "planner", "note": "reply to my clarifying question; planning the completed question", "question": asked})
    # NEW (18 Nov 2026): a bare year or company right after an answered SUMMARY asks for the same summary again
    # ("FY25-26" after "HUL business performance FY24-25"). The remembered summary request is repeated with
    # the new year / company in place of the old one.
    # WHY: the slots kept after an answer are company, year, scope, metric and item. A summary has no metric or
    #      item, so "FY23-24" typed after a summary was treated as a figure follow-up with no figure, and the
    #      agent asked "Which figure or ratio would you like?". It should have been read as "the same summary for
    #      that year", and refused, because there is no FY2023-24 report. The refusal leaves memory untouched,
    #      so a valid year typed next still gives the summary.
    last_summary = memory.get(session_id).get("_summary")
    if asked == question and last_summary and planner.only_company_or_year(question):
        asked = planner.merge_reply(last_summary, question)
        trace.append({"node": "planner", "note": "same summary for another year or company", "question": asked})
    # NEW (18 Nov 2026, later): a bare TOPIC right after an answered summary ("key risks" after "HUL business
    # performance FY24-25") is a summary of that topic for the same company and year.
    # WHY: the follow-up rules were written for figures. "key risks" names no company, so the agent would ask
    #      "Which company do you mean?" although the conversation was plainly about one company and one year.
    #      The company and year come from memory unless the message gives its own; the answer carries the usual
    #      note that they were taken from the previous question.
    carried_topic = False
    if asked == question and last_summary and slots.get("companies") and slots.get("fiscal_years") \
            and planner.only_summary_topic(question):
        base = f"Summarise for {slots['companies'][0]} in {fy_label(slots['fiscal_years'][-1])}"
        asked = planner.merge_reply(base, question)
        carried_topic = not (find_companies(question) and years_in(question))
        trace.append({"node": "planner", "note": "new summary topic, same company and year", "question": asked})
    try:
        # OLD: draft = planner.draft_plan(question, slots, llm)   ...   plan = planner.resolve(draft, question, slots)
        draft = planner.draft_plan(asked, slots, llm)
        trace.append({"node": "planner", "model_slots": draft.model_dump(exclude_none=True)})
        plan = planner.resolve(draft, asked, slots)
    except planner.Clarify as c:
        trace.append({"node": "planner", "clarify": str(c)})
        memory.set_pending(session_id, asked)           # NEW (17 Nov 2026): keep what was asked, for the reply
        return done(AgentAnswer(status="clarify", clarifying_question=str(c), answer=str(c)))
    except planner.Refuse as r:
        trace.append({"node": "planner", "refused": r.reason})
        # NEW (18 Nov 2026): if the user was answering my clarifying question and the reply could not be used
        # (a mistyped or out-of-range year, a company I do not cover), keep the unfinished question so the next
        # message can still complete it.
        # WHY: "summarize ... for HUL" -> "Business Performance" -> "FY2024=25" (a typo) was refused, and the
        #      unfinished question was thrown away. The corrected "FY2024-25" then had nothing to complete and
        #      was attached to an older question about bank deposits.
        if pending and asked != question and r.reason == "not_in_corpus":
            memory.set_pending(session_id, pending)
            trace.append({"node": "planner", "note": "reply not usable; still waiting for an answer to my question"})
            return done(AgentAnswer(status="refused", refusal_reason=r.reason, answer=f"{r} Please give it again."))
        return done(AgentAnswer(status="refused", refusal_reason=r.reason, answer=str(r)))
    except Exception as e:  # noqa: BLE001  malformed model output after instructor's retries, endpoint failure
        trace.append({"node": "planner", "error": str(e)[:200]})
        return done(AgentAnswer(status="escalated", answer="I could not plan an answer to that question. Please rephrase it."))
    trace.append({"node": "planner", "plan": plan.model_dump(exclude_none=True)})
    steps = planner.build_steps(plan)

    # 3. executor (tools)
    runner = Run(plan, llm, trace)
    try:
        result = runner.execute(steps)
    except ToolError as e:
        # NEW (19 Nov 2026, later): the report itself says the thing asked about does not exist (executor.NotApplicable).
        if isinstance(e, NotApplicable):
            return done(AgentAnswer(status="refused", refusal_reason="not_applicable", intent=plan.intent, companies=plan.companies,
                                    fiscal_years=plan.fiscal_years, citations=[e.citation], answer=f"{e}."))
        if "not in the corpus" in str(e):
            return done(AgentAnswer(status="refused", refusal_reason="not_in_corpus", answer=str(e)))
        pages = sorted({f.citation for f in runner.figures if f.citation})
        hint = f" Figures found so far are on {', '.join(pages)}." if pages else ""
        return done(AgentAnswer(status="escalated", intent=plan.intent, companies=plan.companies,
                                fiscal_years=plan.fiscal_years, inputs=runner.figures, citations=pages,
                                answer=f"I could not complete this reliably: {e}.{hint} Please check the report."))
    except Escalate as e:
        return done(AgentAnswer(status="escalated", answer=f"I stopped before finishing: {e}"))
    except Exception as e:  # noqa: BLE001  e.g. the model call inside a reported-figure lookup failed
        trace.append({"node": "executor", "error": str(e)[:200]})
        return done(AgentAnswer(status="escalated", answer="I could not complete this reliably. Please try again."))
    if over_budget():
        return done(AgentAnswer(status="escalated", answer="I stopped because the token budget for one question was used up."))

    # 4. writer + 5. critic (rewrite at most twice; the last attempt is the code template)
    # OLD: expected = writer.formula_for(plan) if plan.intent != "summary" else None
    expected = writer.formula_for(plan, result) if plan.intent != "summary" else None      # 19 Nov 2026: + result
    verdict = None
    for attempt in range(MAX_REWRITES + 1):
        try:
            if plan.intent == "summary":
                ans = writer.write_summary(plan, result, llm)
            else:
                ans = writer.write(plan, result, llm, use_model=use_model_wording and attempt < MAX_REWRITES)
        except Exception as e:  # noqa: BLE001
            trace.append({"node": "writer", "attempt": attempt + 1, "error": str(e)[:200]})
            continue
        verdict = critic.review(ans, plan, result, expected_formula=expected)
        trace.append({"node": "critic", "attempt": attempt + 1, "ok": verdict.ok, "reasons": verdict.reasons})
        if verdict.ok:
            ans.verified = True
            # NEW (17 Nov 2026): say so when the company or year was not in the question but came from memory.
            # OLD: if plan.is_follow_up and not (find_companies(asked) and years_in(asked)):
            # NEW (18 Nov 2026, later): also when a new summary topic reused the remembered company and year.
            if carried_topic or (plan.is_follow_up and not (find_companies(asked) and years_in(asked))):
                ans.caveats.append("Company or year not stated in the question; taken from the previous question.")
            # OLD:
            # memory.save(session_id, {"companies": plan.companies, "fiscal_years": plan.fiscal_years, "scope": plan.scope,
            #                          "metric": plan.metric, "item": plan.item, "intent": plan.intent})
            # NEW (18 Nov 2026): after a summary, the full text of the request is kept too (see "last_summary" above).
            memory.save(session_id, {"companies": plan.companies, "fiscal_years": plan.fiscal_years, "scope": plan.scope,
                                     "metric": plan.metric, "item": plan.item, "intent": plan.intent,
                                     # OLD: "_summary": asked if plan.intent == "summary" else None})
                                     # NEW (19 Nov 2026): a share read from the report text is kept the same way, so
                                     # "and FY2024-25?" repeats the whole question for the other year.
                                     "_summary": asked if plan.intent == "summary" or plan.metric == planner.TEXT_RATIO else None})
            return done(ans)
        if over_budget():
            break
    pages = ", ".join(sorted({f.citation for f in result.get("figures", []) if f.citation})) or "the report"
    why = "; ".join(verdict.reasons) if verdict else "the answer could not be written"
    return done(AgentAnswer(status="escalated", intent=plan.intent, companies=plan.companies, fiscal_years=plan.fiscal_years,
                            inputs=result.get("figures", []), answer=f"Unverified, please check {pages}. ({why})"))
