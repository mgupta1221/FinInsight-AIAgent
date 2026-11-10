"""VectorStore interface — a common contract so the backend is swappable (Qdrant default)."""
from __future__ import annotations
from typing import Protocol


class VectorStore(Protocol):
    def upsert(self, ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None: ...
    def search(self, vector: list[float], top_k: int, flt: dict | None = None) -> list[dict]: ...
