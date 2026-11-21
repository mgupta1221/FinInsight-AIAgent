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
        # NEW (15 Nov 2026): close the client when Python exits.
        # WHY: with a local folder store (QDRANT_URL=./store/qdrant) the client was closed only by Python's
        #      final clean-up, which printed "Exception ignored ... ImportError: sys.meta_path is None,
        #      Python is likely shutting down" after every answer. The answer was not affected, but the
        #      message looks like a failure. Closing it a moment earlier (atexit) avoids the message.
        import atexit
        atexit.register(self._close_quietly)

    def _close_quietly(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001  (already closed, or the interpreter is half shut down)
            pass

    def ensure_collection(self, dim: int) -> None:
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )
            logger.info("created Qdrant collection %s (dim=%d)", self.collection, dim)

    # NEW (18 Nov 2026): used by the ingest so that a re-run replaces the index and does not double it.
    def drop_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
            logger.info("removed Qdrant collection %s (it is rebuilt by this run)", self.collection)

    def delete_where(self, flt: dict) -> None:
        """Delete every point whose payload matches `flt`, e.g. {"ticker": "INFY"}."""
        self.client.delete(collection_name=self.collection,
                           points_selector=models.FilterSelector(filter=self._build_filter(flt)))

    def upsert(self, vectors: list[list[float]], payloads: list[dict]) -> int:
        # CHANGED (18 Nov 2026): the point id is derived from the chunk id.
        # OLD: models.PointStruct(id=str(uuid.uuid4()), vector=v, payload=p)
        # WHY: a random id made every re-index ADD a second copy of each chunk. With an id computed from the
        #      chunk's own id, indexing the same chunk again overwrites the first copy. Payloads without an
        #      "id" (none in this project) still get a random one.
        points = [
            models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, str(p["id"]))) if p.get("id") else str(uuid.uuid4()),
                               vector=v, payload=p)
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
