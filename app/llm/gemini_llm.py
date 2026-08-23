"""Gemini LLM adapter (optional, lazy import of google-genai)."""

from __future__ import annotations

import json
import os

from app.llm.base import BaseLLM, LLMError, format_history, is_retryable_llm_error, retry_transient
from app.llm.prompts import CLASSIFY_SYSTEM, SYSTEM_PROMPT
from app.schemas import RetrievedChunk

_SYSTEM = SYSTEM_PROMPT
_CLASSIFY_SYSTEM = CLASSIFY_SYSTEM


def _thinking_budget(default: int = 512) -> int | None:
    """Reasoning budget for 2.5 models; -1 disables thinking entirely."""
    raw = os.environ.get("GEMINI_THINKING_BUDGET", str(default)).strip()
    try:
        val = int(raw)
    except ValueError:
        return default
    if val < 0:
        return None
    return val


class GeminiLLM(BaseLLM):
    name = "gemini"

    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-2.5-flash",
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai  # type: ignore

                kwargs: dict = {
                    "api_key": self.api_key,
                    # google-genai v2 expects http timeout in MILLISECONDS
                    "http_options": {"timeout": int(self.timeout_seconds * 1000)},
                }
                # New-format Google Cloud API keys ("AQ....") are Vertex AI
                # express-mode credentials: they only work through the Vertex
                # backend, not the Gemini-API developer endpoint.
                if self.api_key.startswith("AQ."):
                    kwargs["vertexai"] = True
                self._client = genai.Client(**kwargs)
            except ImportError as exc:
                raise LLMError(
                    "google-genai not installed. pip install -r requirements-optional.txt"
                ) from exc
            except Exception as exc:
                raise LLMError(f"Failed to init Gemini client: {exc}") from exc
        return self._client

    def generate_answer(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        max_chars: int = 2000,
        history: Optional[list[dict]] = None,
    ) -> dict:
        if not self.available:
            raise LLMError("GEMINI_API_KEY is not set (LLM_BACKEND=gemini).")
        context = "\n\n".join(
            f"[source_id={c.source_id}|chunk_id={c.chunk_id}]\n{c.text}" for c in chunks
        )
        history_block = format_history(history)
        user = (
            (f"{history_block}\n\n" if history_block else "")
            + f"Câu hỏi: {query}\n\n"
            f"Các đoạn nguồn (chỉ được dùng các source_id này):\n{context}\n\n"
            f"Giới hạn câu trả lời: {max_chars} ký tự."
        )
        client = self._get_client()
        gen_cfg: dict = {
            "response_mime_type": "application/json",
            "temperature": 0.2,
        }
        budget = _thinking_budget()
        if self.model.startswith("gemini-2.5") and budget is not None:
            gen_cfg["thinking_config"] = {"thinking_budget": budget}
        try:
            response = retry_transient(
                lambda: client.models.generate_content(
                    model=self.model,
                    contents=[
                        {
                            "role": "user",
                            "parts": [{"text": _SYSTEM}, {"text": user}],
                        }
                    ],
                    config=gen_cfg,
                ),
                max_retries=self.max_retries,
                timeout_seconds=self.timeout_seconds,
                backoff_seconds=self.backoff_seconds,
                retryable=is_retryable_llm_error,
            )
        except Exception as exc:
            raise LLMError(f"Gemini request failed after retries: {exc}") from exc
        text = response.text.strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            # Not retryable: a fresh call fails the same way (F/T3 fix).
            raise LLMError(f"Gemini returned non-JSON output: {exc}") from exc
        parsed.setdefault("source_ids", [])
        parsed.setdefault("limitations", [])
        parsed.setdefault("next_step", "")
        # NOTE: raw source_ids are deliberately NOT filtered here (F2 fix);
        # the pipeline validates raw citations, then sanitizes.
        return parsed

    def classify_safe(self, query: str, chunks: list[RetrievedChunk]) -> bool:
        """LLM-based safety classification (router step 7, cloud mode only).

        Conservative: any failure or non-JSON output means NOT safe.
        """
        if not self.available:
            return False
        client = self._get_client()
        try:
            response = retry_transient(
                lambda: client.models.generate_content(
                    model=self.model,
                    contents=[{"role": "user", "parts": [{"text": _CLASSIFY_SYSTEM}, {"text": query[:2000]}]}],
                    config={
                        "response_mime_type": "application/json",
                        "temperature": 0.0,
                        "thinking_config": {"thinking_budget": 0},
                    },
                ),
                max_retries=self.max_retries,
                timeout_seconds=self.timeout_seconds,
                backoff_seconds=self.backoff_seconds,
                retryable=is_retryable_llm_error,
            )
            parsed = json.loads(response.text.strip())
            return bool(parsed.get("safe", False))
        except Exception:
            return False
