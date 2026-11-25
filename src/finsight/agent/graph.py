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
        use_model_wording: bool = True, on_stage=None) -> AgentAnswer:
    # NEW (22 Nov 2026): `on_stage`, an optional function the caller gives to be told what the agent is doing NOW.
    # WHY: a question that needs the model several times takes 10 to 30 seconds, and the screen showed only
    #      "Working on it...". The app passes a function that prints each stage as it starts (guard, planner,
    #      executor steps, writer, critic). It is called with two texts: the stage name and one plain sentence.
    #      It only reports; it decides nothing. With on_stage=None (the evaluation, the tests) nothing changes.
    def tell(stage: str, message: str) -> None:
        if on_stage is not None:
            try:
                on_stage(stage, message)
            except Exception:  # noqa: BLE001  a display problem must never stop an answer
                pass
    if llm is None:
        from finsight.agent.llm_adapter import RealLLM
        llm = RealLLM()
    memory = memory or Memory()
    question = clean_question(question)
    # OLD: trace: list[dict] = []
    # CHANGED (22 Nov 2026): the same list, which also reports each executor step when it is added (see on_stage).
    class _Trace(list):
        def append(self, entry):  # noqa: ANN001
            super().append(entry)
            if isinstance(entry, dict) and "step" in entry and "do" in entry:
                args = entry.get("args") or {}
                about = " ".join(str(args[k]) for k in ("company", "fiscal_year") if args.get(k))
                tell("executor", f"Step {entry['step']}: {str(entry['do']).replace('_', ' ')}" + (f" ({about})" if about else ""))
    trace: list[dict] = _Trace()

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
    tell("guard", "Checking that the question is about the reports and is not a request for advice")
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
    # NEW (24 Nov 2026): "no" in reply to a question of the agent drops the unfinished question.
    # WHY: a reply is joined to the question it answers. "no" joined to "... Would you like the net profit instead?"
    #      was read as part of that question and answered it. A bare "no" now ends it.
    if pending and planner.declines(question):
        msg = "No problem. What would you like to know instead?"
        trace.append({"node": "planner", "note": "the user said no to my question; the unfinished question is dropped"})
        return done(AgentAnswer(status="clarify", clarifying_question=msg, answer=msg))
    # NEW (24 Nov 2026, later): "No. Revenue from operations" = no to my question, and a new question after it.
    # WHY: see planner.declines_then(). The unfinished question is dropped and only the part after the "no" is
    #      planned. Company and year come from memory as for any follow-up (see the loss block below, which now
    #      remembers them).
    if pending and planner.declines_then(question):
        question = planner.declines_then(question)
        pending = None
        trace.append({"node": "planner", "note": "the user said no to my question and asked something else", "question": question})

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
        tell("planner", "Working out the company, the year and what is asked")
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
    tell("executor", f"Collecting the figures or passages from the reports ({len(steps)} step{'s' if len(steps) != 1 else ''})")
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

    # NEW (24 Nov 2026, mentor's review): asked for a LOSS, and the figure read from the report is a PROFIT.
    # WHY: see planner.asks_for_loss(). The figure is read first, so the reply is based on the report and not on
    #      a guess; if the company really made a loss (a negative figure), the answer is given as usual. The
    #      question, reworded for the net profit, is kept for one reply, so "yes" or "net profit" completes it.
    if plan.intent == "fact" and plan.item == "net_profit" and planner.asks_for_loss(asked):
        read = [v.get("value") for v in result.get("values", {}).values()]
        if read and all(isinstance(v, (int, float)) and v > 0 for v in read):
            from finsight.tools.get_company_profile import get_company_profile
            names = " and ".join(get_company_profile(t)["name"] for t in plan.companies)
            year = fy_label(plan.fiscal_years[-1]) if plan.fiscal_years else "that year"
            msg = (f"{names} did not report a loss in {year}; {'it' if len(plan.companies) == 1 else 'they'} reported a net profit. "
                   "Would you like the net profit instead?")
            # NEW (24 Nov 2026, later): remember the company, year and scope of this question.
            # WHY: memory was written only after an answer. After "what are the losses of Infosys for 25-26" and
            #      "no", the next message "Revenue from operation" found no company and no year, and the agent
            #      asked for both although the user had just named them. The question was understood and its
            #      figure was read from the report, so its company and year are safe to carry over. The figure
            #      itself (net profit) is NOT remembered: the user has not accepted it yet.
            memory.save(session_id, {"companies": plan.companies, "fiscal_years": plan.fiscal_years, "scope": plan.scope,
                                     "metric": None, "item": None, "intent": plan.intent})
            memory.set_pending(session_id, planner.loss_as_profit(asked))
            trace.append({"node": "planner", "note": "a loss was asked for; the figure read is a profit", "clarify": msg})
            return done(AgentAnswer(status="clarify", intent=plan.intent, companies=plan.companies, fiscal_years=plan.fiscal_years,
                                    clarifying_question=msg, answer=msg))

    # 4. writer + 5. critic (rewrite at most twice; the last attempt is the code template)
    # OLD: expected = writer.formula_for(plan) if plan.intent != "summary" else None
    expected = writer.formula_for(plan, result) if plan.intent != "summary" else None      # 19 Nov 2026: + result
    verdict = None
    for attempt in range(MAX_REWRITES + 1):
        tell("writer", "Writing the answer" + (f" again (attempt {attempt + 1})" if attempt else ""))
        try:
            if plan.intent == "summary":
                # OLD: ans = writer.write_summary(plan, result, llm)
                # NEW (21 Nov 2026): on a second or third attempt the writer is told why the last one was rejected.
                ans = writer.write_summary(plan, result, llm, feedback="; ".join(verdict.reasons) if verdict and not verdict.ok else "")
            else:
                ans = writer.write(plan, result, llm, use_model=use_model_wording and attempt < MAX_REWRITES)
        except Exception as e:  # noqa: BLE001
            trace.append({"node": "writer", "attempt": attempt + 1, "error": str(e)[:200]})
            continue
        tell("critic", "Checking every number and citation against the pages")
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
