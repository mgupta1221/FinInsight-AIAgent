"""Keyword (BM25) search over the persisted chunks file (data/parsed/chunks.jsonl).

Loaded lazily and cached. Metadata filtering is applied in Python (the chunk corpus is small).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi

from finsight.config import settings


# NEW (18 Nov 2026): one tokeniser for the chunks and for the query.
# WHY: text was split on spaces only. Punctuation stayed glued to the words, so the query word "infosys'" never
#      matched "infosys" and "fy2025-26?" never matched "fy2025-26"; and with no stop-word list, "what", "was",
#      "in", "from" decided the ranking. In the search comparison (eval/retrieval_experiment.py, 72 cases) keyword
#      search found the right page in the first 10 results for 4% of the questions, and it dragged the hybrid
#      result below vector search alone. Words are now letters-and-digits runs, and common words are dropped.
_STOP = set("""a an the of for in on at to by from with and or is are was were be been do does did has have had what which
    who how when where why its it this that these those as than then there here i we you me our your their can could
    would will shall please tell show give per vs""".split())
_WORD = re.compile(r"[a-z0-9]+")


def tokenise(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


@lru_cache(maxsize=1)
def _load_corpus() -> tuple[list[dict], BM25Okapi]:
    path = settings.data_dir / "parsed" / "chunks.jsonl"
    chunks: list[dict] = []
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            chunks = [json.loads(line) for line in fh if line.strip()]
    # OLD: tokenised = [c["text"].lower().split() for c in chunks] or [[""]]
    tokenised = [tokenise(c["text"]) for c in chunks] or [[""]]
    return chunks, BM25Okapi(tokenised)


def _passes(chunk: dict, flt: dict | None) -> bool:
    return not flt or all(chunk.get(k) == v for k, v in flt.items())


def bm25_search(query: str, top_k: int = 10, flt: dict | None = None) -> list[dict]:
    chunks, bm25 = _load_corpus()
    if not chunks:
        return []
    # OLD: scores = bm25.get_scores(query.lower().split())
    scores = bm25.get_scores(tokenise(query))
    ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
    out = [{"score": float(s), **c} for s, c in ranked if _passes(c, flt)]
    return out[:top_k]
