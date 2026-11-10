"""Tool: search_report — hybrid retrieval over the report text.

Combines dense (meaning) + BM25 (keyword) search, fuses with RRF, then reranks — always filtering by
company / fiscal year / statement / scope FIRST so it never returns the wrong year. Used for note
disclosures and qualitative questions, and as the fallback when a figure isn't in the store.
Returns ranked passages with their page + citation.
"""

from __future__ import annotations

from finsight.retrieval.bm25 import bm25_search
from finsight.retrieval.dense import dense_search
from finsight.retrieval.filters import build_filter
from finsight.retrieval.hybrid import rrf_fuse
from finsight.retrieval.qdrant_store import QdrantStore
from finsight.retrieval.reranker import rerank
from finsight.tools.base import register

_store: QdrantStore | None = None


def _get_store() -> QdrantStore:
    global _store
    if _store is None:
        _store = QdrantStore()
    return _store


def _citation(hit: dict) -> str:
    yy = str(hit.get("fiscal_year", "")).replace("-", "")[2:]
    return f"{hit.get('ticker','?')}-FY{yy}-p{hit.get('page','?')}"


@register("search_report")
def search_report(
    query: str,
    company: str | None = None,
    fiscal_year: str | None = None,
    statement: str | None = None,
    scope: str | None = None,
    top_k: int = 5,
    pool: int = 20,
) -> list[dict]:
    """Return up to top_k passages: {text, page, citation, ticker, fiscal_year, section, score}."""
    from finsight.tools.get_company_profile import get_company_profile

    ticker = get_company_profile(company)["ticker"] if company else None
    flt = build_filter(company=ticker, fiscal_year=fiscal_year, statement=statement, scope=scope)

    dense_hits = dense_search(_get_store(), query, top_k=pool, flt=flt)
    bm25_hits = bm25_search(query, top_k=pool, flt=flt)
    fused = rrf_fuse([dense_hits, bm25_hits], key="id")
    reranked = rerank(query, fused, top_k=top_k)

    return [
        {
            "text": h["text"],
            "page": h.get("page"),
            "citation": _citation(h),
            "ticker": h.get("ticker"),
            "fiscal_year": h.get("fiscal_year"),
            "section": h.get("section"),
            "score": h.get("rerank", h.get("rrf", h.get("score"))),
        }
        for h in reranked
    ]
