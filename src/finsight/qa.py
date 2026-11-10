"""Week-1 grounded question answering (retrieve -> read -> answer with citation).

This is the simple RAG path the Week-1 chat uses: retrieve the most relevant passages for the
question (filtered by company/year when known), then ask the model to answer USING ONLY those
passages and to cite the page. If nothing relevant is found, it says so rather than inventing a
figure. The full Planner→Executor→Writer→Critic agent replaces this in Week 2.
"""

from __future__ import annotations

from finsight.llm import chat
from finsight.tools.search_report import search_report

SYSTEM = (
    "You are FinSight, a financial-report assistant. Answer ONLY using the provided excerpts from "
    "company annual reports. Every figure must come from an excerpt, and you must cite the page "
    "using the bracketed citation shown with each excerpt (e.g. [INFY-FY2425-p30]). State the unit "
    "and fiscal year. If the excerpts do not contain the answer, say you could not find it in the "
    "report — do not guess. Do not give investment advice."
)


def _context(passages: list[dict]) -> str:
    blocks = []
    for p in passages:
        blocks.append(f"[{p['citation']}] (page {p['page']}, {p.get('section','')})\n{p['text']}")
    return "\n\n---\n\n".join(blocks)


def answer_question(
    question: str,
    company: str | None = None,
    fiscal_year: str | None = None,
    top_k: int = 5,
) -> dict:
    """Return {answer, passages, used_context}. Retrieval is filtered when company/year are given."""
    passages = search_report(question, company=company, fiscal_year=fiscal_year, top_k=top_k)
    if not passages:
        return {
            "answer": "I could not find anything relevant in the report corpus for that question.",
            "passages": [],
            "used_context": False,
        }
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Question: {question}\n\nExcerpts:\n{_context(passages)}"},
    ]
    answer = chat(messages)
    return {"answer": answer, "passages": passages, "used_context": True}
