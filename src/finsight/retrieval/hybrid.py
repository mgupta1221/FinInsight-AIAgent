"""Combine dense + BM25 result lists with Reciprocal Rank Fusion (RRF, k=60)."""
from __future__ import annotations


def rrf_fuse(result_lists: list[list[dict]], k: int = 60, key: str = "id") -> list[dict]:
    scores: dict = {}
    best: dict = {}
    for results in result_lists:
        for rank, item in enumerate(results):
            ident = item.get(key) or item.get("text")
            scores[ident] = scores.get(ident, 0.0) + 1.0 / (k + rank + 1)
            best.setdefault(ident, item)
    fused = [{**best[i], "rrf": s} for i, s in sorted(scores.items(), key=lambda x: x[1], reverse=True)]
    return fused
