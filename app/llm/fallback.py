"""Fallback LLM: try the primary backend, then the fallback (F4).

Used when LLM_FALLBACK_BACKEND=gemini is set next to LLM_BACKEND=groq.
Semantics:
- generate_answer: primary wins; fallback only on LLMError.
- classify_safe: conservative — a failed primary falls through to the
  fallback's own (also conservative) decision; total failure = NOT safe.
"""

from __future__ import annotations

from typing import Optional

from app.llm.base import BaseLLM, LLMError
from app.schemas import RetrievedChunk


class FallbackLLM(BaseLLM):
    name = "fallback"

    def __init__(self, primary: BaseLLM, fallback: BaseLLM):
        self.primary = primary
        self.fallback = fallback
        self._last_served: BaseLLM | None = None

    @property
    def available(self) -> bool:
        return self.primary.available or self.fallback.available

    @property
    def active_name(self) -> str:
        return f"{self.primary.name}->{self.fallback.name}"

    @property
    def last_usage(self) -> dict:
        """Usage of the backend that actually served the last call (R25)."""
        if self._last_served is not None:
            return dict(getattr(self._last_served, "last_usage", {}) or {})
        return {}

    def generate_answer(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        max_chars: int = 2000,
        history: Optional[list[dict]] = None,
    ) -> dict:
        try:
            out = self.primary.generate_answer(
                query, chunks, max_chars=max_chars, history=history
            )
            self._last_served = self.primary
            return out
        except LLMError as primary_error:
            if not self.fallback.available:
                raise LLMError(
                    f"Primary {self.primary.name} failed ({primary_error}); "
                    "no fallback configured/available."
                ) from primary_error
            try:
                out = self.fallback.generate_answer(
                    query, chunks, max_chars=max_chars, history=history
                )
                self._last_served = self.fallback
                return out
            except LLMError as fallback_error:
                raise LLMError(
                    f"Primary {self.primary.name} failed ({primary_error}); "
                    f"fallback {self.fallback.name} failed ({fallback_error})."
                ) from fallback_error

    def classify_safe(self, query: str, chunks: list[RetrievedChunk]) -> bool:
        try:
            return self.primary.classify_safe(query, chunks)
        except Exception:
            return self.fallback.classify_safe(query, chunks)
