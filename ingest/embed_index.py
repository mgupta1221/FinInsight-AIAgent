"""Embed chunks with the local bge model and upsert them into Qdrant.

Also writes the chunk corpus to data/parsed/chunks.jsonl so the BM25 keyword index can read it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from finsight import embeddings
from finsight.config import settings
from finsight.retrieval.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


def write_chunk_corpus(chunks: list[dict]) -> Path:
    out = settings.data_dir / "parsed" / "chunks.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    return out


def index_chunks(chunks: list[dict], store: QdrantStore | None = None, batch: int = 128) -> int:
    """Embed and upsert all chunks into Qdrant. Returns the number of points indexed."""
    if not chunks:
        logger.warning("no chunks to index")
        return 0
    store = store or QdrantStore()
    store.ensure_collection(embeddings.embedding_dim())
    total = 0
    for i in range(0, len(chunks), batch):
        part = chunks[i : i + batch]
        vectors = embeddings.encode([c["text"] for c in part])
        payloads = [{k: v for k, v in c.items()} for c in part]
        total += store.upsert(vectors, payloads)
        logger.info("indexed %d/%d chunks", min(i + batch, len(chunks)), len(chunks))
    return total
