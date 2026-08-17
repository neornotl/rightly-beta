"""Base retriever interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas import RetrievedChunk


class Retriever(ABC):
    """Interface for retrieval backends."""

    name: str = "base"

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """Return top-k retrieved chunks ranked by descending relevance."""
