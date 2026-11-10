"""Dense (meaning) search: embed the query, search Qdrant with metadata filters."""
from __future__ import annotations

from finsight import embeddings


def dense_search(store, query: str, top_k: int = 10, flt: dict | None = None) -> list[dict]:
    qvec = embeddings.encode([query])[0]
    return store.search(qvec, top_k=top_k, flt=flt)
