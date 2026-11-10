"""Keyword (BM25) search over the persisted chunks file (data/parsed/chunks.jsonl).

Loaded lazily and cached. Metadata filtering is applied in Python (the chunk corpus is small).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi

from finsight.config import settings


@lru_cache(maxsize=1)
def _load_corpus() -> tuple[list[dict], BM25Okapi]:
    path = settings.data_dir / "parsed" / "chunks.jsonl"
    chunks: list[dict] = []
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            chunks = [json.loads(line) for line in fh if line.strip()]
    tokenised = [c["text"].lower().split() for c in chunks] or [[""]]
    return chunks, BM25Okapi(tokenised)


def _passes(chunk: dict, flt: dict | None) -> bool:
    return not flt or all(chunk.get(k) == v for k, v in flt.items())


def bm25_search(query: str, top_k: int = 10, flt: dict | None = None) -> list[dict]:
    chunks, bm25 = _load_corpus()
    if not chunks:
        return []
    scores = bm25.get_scores(query.lower().split())
    ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
    out = [{"score": float(s), **c} for s, c in ranked if _passes(c, flt)]
    return out[:top_k]
