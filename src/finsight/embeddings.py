"""Local embedding + reranker models (no embeddings endpoint is provided).

Primary: BAAI bge via sentence-transformers (settings.embedding_model / reranker_model), loaded
lazily on first use. If sentence-transformers / torch is not installed, a lightweight, deterministic
**hashing fallback** keeps the whole pipeline runnable (clearly logged) — install the real model for
production-quality retrieval. Both paths share the same vector space within a run.
"""

from __future__ import annotations

import hashlib
import logging
import math

from finsight.config import settings

logger = logging.getLogger(__name__)

_embed_model = None
_rerank_model = None
_use_fallback = False


def _load_embed():
    global _embed_model, _use_fallback
    if _embed_model is not None or _use_fallback:
        return
    try:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer(settings.embedding_model)
        logger.info("loaded embedding model %s", settings.embedding_model)
    except Exception as e:  # noqa: BLE001
        _use_fallback = True
        logger.warning(
            "sentence-transformers unavailable (%s); using hashing-embedding FALLBACK "
            "(install sentence-transformers for real bge quality)", e
        )


def _hash_embed(text: str, dim: int) -> list[float]:
    """Deterministic bag-of-words hashing embedding, L2-normalised. Dependency-free fallback."""
    vec = [0.0] * dim
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def encode(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts into vectors (length settings.embedding_dim)."""
    _load_embed()
    if _use_fallback:
        return [_hash_embed(t, settings.embedding_dim) for t in texts]
    return [v.tolist() for v in _embed_model.encode(texts, normalize_embeddings=True)]


def embedding_dim() -> int:
    _load_embed()
    if _use_fallback:
        return settings.embedding_dim
    return _embed_model.get_sentence_embedding_dimension()


def rerank(query: str, passages: list[str]) -> list[float]:
    """Score each passage against the query (higher = more relevant)."""
    if not passages:
        return []
    global _rerank_model
    try:
        if _rerank_model is None:
            from sentence_transformers import CrossEncoder

            _rerank_model = CrossEncoder(settings.reranker_model)
        scores = _rerank_model.predict([(query, p) for p in passages])
        return [float(s) for s in scores]
    except Exception as e:  # noqa: BLE001
        logger.warning("reranker unavailable (%s); falling back to token-overlap scores", e)
        q = set(query.lower().split())
        return [len(q & set(p.lower().split())) / (len(q) or 1) for p in passages]
