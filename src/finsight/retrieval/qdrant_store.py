"""Qdrant implementation of the vector store.

Dense search with payload (metadata) filters on company / fiscal_year / statement / scope / section.
Works three ways so it runs anywhere:
  - a running server at settings.qdrant_url (Docker, default),
  - an on-disk local store (path=...),
  - fully in-memory (":memory:") for tests.
"""

from __future__ import annotations

import logging
import uuid

from qdrant_client import QdrantClient, models

from finsight.config import settings

logger = logging.getLogger(__name__)


class QdrantStore:
    def __init__(self, collection: str | None = None, location: str | None = None):
        self.collection = collection or settings.qdrant_collection
        if location == ":memory:":
            self.client = QdrantClient(location=":memory:")
        elif location:
            self.client = QdrantClient(path=location)
        elif settings.qdrant_url.startswith("http"):
            self.client = QdrantClient(url=settings.qdrant_url)
        else:
            self.client = QdrantClient(path=settings.qdrant_url)

    def ensure_collection(self, dim: int) -> None:
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )
            logger.info("created Qdrant collection %s (dim=%d)", self.collection, dim)

    def upsert(self, vectors: list[list[float]], payloads: list[dict]) -> int:
        points = [
            models.PointStruct(id=str(uuid.uuid4()), vector=v, payload=p)
            for v, p in zip(vectors, payloads)
        ]
        self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    @staticmethod
    def _build_filter(flt: dict | None) -> models.Filter | None:
        if not flt:
            return None
        must = [
            models.FieldCondition(key=k, match=models.MatchValue(value=v))
            for k, v in flt.items()
            if v is not None
        ]
        return models.Filter(must=must) if must else None

    def search(self, vector: list[float], top_k: int = 10, flt: dict | None = None) -> list[dict]:
        hits = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=top_k,
            query_filter=self._build_filter(flt),
            with_payload=True,
        ).points
        return [{"score": h.score, **(h.payload or {})} for h in hits]

    def count(self) -> int:
        return self.client.count(self.collection).count
