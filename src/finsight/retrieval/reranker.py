"""Re-rank fused hits with the bge cross-encoder (falls back to token overlap if unavailable)."""
from __future__ import annotations

from finsight import embeddings


def rerank(query: str, hits: list[dict], top_k: int = 5) -> list[dict]:
    if not hits:
        return []
    scores = embeddings.rerank(query, [h["text"] for h in hits])
    reranked = [{**h, "rerank": float(s)} for h, s in zip(hits, scores)]
    reranked.sort(key=lambda h: h["rerank"], reverse=True)
    return reranked[:top_k]
