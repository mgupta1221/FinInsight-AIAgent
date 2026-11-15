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
from finsight.agent.executor import Escalate, Run
from finsight.agent.guard import guard
from finsight.agent.memory import Memory
from finsight.config import settings
from finsight.safety.pii import mask_pii
from finsight.safety.sanitiser import clean_question
from finsight.schemas import AgentAnswer
from finsight.tools.base import ToolError

MAX_REWRITES = 2


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

    # 1. guard (code only, no tokens)
    refused = guard(question, trace)
    if refused:
        return done(refused)

    # 2. planner (model fills slots; code validates them)
    slots = memory.get(session_id)
    try:
        draft = planner.draft_plan(question, slots, llm)
        trace.append({"node": "planner", "model_slots": draft.model_dump(exclude_none=True)})
        plan = planner.resolve(draft, question, slots)
    except planner.Clarify as c:
        trace.append({"node": "planner", "clarify": str(c)})
        return done(AgentAnswer(status="clarify", clarifying_question=str(c), answer=str(c)))
    except planner.Refuse as r:
        trace.append({"node": "planner", "refused": r.reason})
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
    expected = writer.formula_for(plan) if plan.intent != "summary" else None
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
            memory.save(session_id, {"companies": plan.companies, "fiscal_years": plan.fiscal_years, "scope": plan.scope,
                                     "metric": plan.metric, "item": plan.item, "intent": plan.intent})
            return done(ans)
        if over_budget():
            break
    pages = ", ".join(sorted({f.citation for f in result.get("figures", []) if f.citation})) or "the report"
    why = "; ".join(verdict.reasons) if verdict else "the answer could not be written"
    return done(AgentAnswer(status="escalated", intent=plan.intent, companies=plan.companies, fiscal_years=plan.fiscal_years,
                            inputs=result.get("figures", []), answer=f"Unverified, please check {pages}. ({why})"))
