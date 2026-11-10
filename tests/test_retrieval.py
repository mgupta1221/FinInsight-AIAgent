"""Retrieval tests: metadata filters restrict to the right company/year; indexing + search work.

Uses an in-memory Qdrant and the built-in fallback embedding, so it runs anywhere with no PDFs,
no server, and no torch.
"""

import pytest

from finsight.retrieval.filters import build_filter
from finsight.retrieval.hybrid import rrf_fuse
from finsight.retrieval.qdrant_store import QdrantStore
from finsight.retrieval.dense import dense_search


def _chunk(cid, ticker, fy, text, page=1):
    return {"id": cid, "ticker": ticker, "fiscal_year": fy, "scope": "consolidated",
            "statement": "pnl", "section": "pnl", "page": page, "text": text}


@pytest.fixture
def store():
    from finsight import embeddings
    s = QdrantStore(collection="test", location=":memory:")
    s.ensure_collection(embeddings.embedding_dim())
    chunks = [
        _chunk("a", "INFY", "2024-25", "Infosys revenue from operations was strong", 30),
        _chunk("b", "INFY", "2025-26", "Infosys revenue from operations grew again", 31),
        _chunk("c", "TCS", "2024-25", "TCS revenue from operations rose", 40),
    ]
    s.upsert(embeddings.encode([c["text"] for c in chunks]),
             [{k: v for k, v in c.items()} for c in chunks])
    return s


def test_filter_by_company_year(store):
    hits = dense_search(store, "revenue from operations", top_k=5,
                        flt=build_filter(company="INFY", fiscal_year="2025-26"))
    assert hits, "expected at least one hit"
    assert all(h["ticker"] == "INFY" and h["fiscal_year"] == "2025-26" for h in hits)


def test_filter_isolates_company(store):
    hits = dense_search(store, "revenue", top_k=5, flt=build_filter(company="TCS"))
    assert all(h["ticker"] == "TCS" for h in hits)


def test_build_filter_drops_none():
    assert build_filter(company="INFY", fiscal_year=None) == {"ticker": "INFY"}


def test_rrf_fuse_combines_ranks():
    a = [{"id": "x"}, {"id": "y"}]
    b = [{"id": "y"}, {"id": "z"}]
    fused = rrf_fuse([a, b], key="id")
    assert fused[0]["id"] == "y"  # appears high in both -> top
