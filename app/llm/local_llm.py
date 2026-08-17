"""Local LLM adapter via Ollama (OpenAI-compatible endpoint, fully offline).

Council R-local: the offline brain. Talks to a local Ollama server
(http://localhost:11434 by default) or any OpenAI-compatible local server
(LM Studio, llama.cpp server, vLLM). Nothing ever leaves the machine.

Model recommendation for the demo machine (i5 + 16GB DDR5 + RTX 3060 Ti 8GB),
council round 26 ruling (luna + nemotron + m365, 2026-08-16):
  OLLAMA_MODEL=qwen2.5:7b-instruct-q4_k_m  (main: ~4.8GB VRAM, JSON-stable,
                                            fast, no thinking tokens; leaves
                                            ~1.5GB headroom for CUDA kernel +
                                            e5-small embedding)
  Fallback:  qwen3:8b                       (better VN quality, needs
                                            think=false, slightly slower)
  Emergency: qwen2.5:3b                     (CPU-only fallback)
  Not recommended: gemma3:12b (7.4GB VRAM - OOM risk on 8GB card)

Qwen3 is a "thinking" model: Ollama >= 0.8 honours ``think=false`` so the
model answers directly instead of emitting a reasoning trace that would
pollute the JSON payload. Passed best-effort via extra_body for qwen3* tags.

Setup (one-time, needs internet; afterwards fully offline):
  ollama serve                  # or install the Ollama desktop app
  ollama pull qwen2.5:7b-instruct-q4_k_m
"""

from __future__ import annotations

import json
import time

from app.llm.base import BaseLLM, LLMError, format_history, is_retryable_llm_error, retry_transient
from app.llm.prompts import CLASSIFY_SYSTEM, SYSTEM_PROMPT
from app.schemas import RetrievedChunk

_SYSTEM = SYSTEM_PROMPT
_CLASSIFY_SYSTEM = CLASSIFY_SYSTEM

_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_k_m"
_AVAILABLE_TTL_S = 30.0


class LocalLLM(BaseLLM):
    """Ollama / any OpenAI-compatible local server, JSON-grounded answers."""

    name = "local"

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ):
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.model = model or _DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._client = None
        self._available: bool | None = None
        self._available_checked_at = 0.0
        self.last_usage: dict = {}

    @property
    def available(self) -> bool:
        """True when a local server answers /models quickly (cached 30s)."""
        now = time.monotonic()
        if self._available is not None and now - self._available_checked_at < _AVAILABLE_TTL_S:
            return self._available
        self._available_checked_at = now
        try:
            import requests

            resp = requests.get(f"{self.base_url}/models", timeout=2.0)
            self._available = resp.status_code < 500
        except Exception:
            self._available = False
        return self._available

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI  # type: ignore

                # Ollama ignores the API key; some compatible servers require one.
                self._client = OpenAI(
                    api_key="ollama",
                    base_url=self.base_url,
                    timeout=self.timeout_seconds,
                    max_retries=0,
                )
            except ImportError as exc:
                raise LLMError(
                    "openai not installed. pip install -r requirements-optional.txt"
                ) from exc
            except Exception as exc:
                raise LLMError(f"Failed to init local LLM client: {exc}") from exc
        return self._client

    def _generate(
        self,
        client,
        messages: list[dict],
        *,
        temperature: float,
        response_format: dict | None = None,
    ) -> str:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "response_format": response_format,
            "temperature": temperature,
        }
        extra: dict = {}
        if self.model.startswith("qwen3"):
            # Qwen3 "thinking" models: answer directly, no reasoning trace.
            extra["think"] = False
        if extra:
            kwargs["extra_body"] = extra
        completion = client.chat.completions.create(**kwargs)
        self.last_usage = {
            "model": getattr(completion, "model", self.model),
            "prompt_tokens": int(getattr(completion.usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(completion.usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(completion.usage, "total_tokens", 0) or 0),
        }
        return completion.choices[0].message.content.strip()

    def generate_answer(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        max_chars: int = 2000,
        history: Optional[list[dict]] = None,
    ) -> dict:
        if not self.available:
            raise LLMError(
                f"Local LLM unreachable at {self.base_url}. Start Ollama "
                f"('ollama serve') and pull the model ('ollama pull {self.model}')."
            )
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
        try:
            text = retry_transient(
                lambda: self._generate(
                    client,
                    [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                ),
                max_retries=self.max_retries,
                timeout_seconds=self.timeout_seconds,
                backoff_seconds=self.backoff_seconds,
                retryable=is_retryable_llm_error,
            )
        except Exception as exc:
            raise LLMError(f"Local LLM request failed after retries: {exc}") from exc
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Local LLM returned non-JSON output: {exc}") from exc
        parsed.setdefault("source_ids", [])
        parsed.setdefault("limitations", [])
        parsed.setdefault("next_step", "")
        chunk_to_source = {c.chunk_id: c.source_id for c in chunks}
        mapped = [chunk_to_source.get(sid, sid) for sid in parsed.get("source_ids", [])]
        parsed["source_ids"] = mapped
        return parsed

    def classify_safe(self, query: str, chunks: list[RetrievedChunk]) -> bool:
        """LLM-based safety classification (cloud mode only; local never uses it).

        Conservative: any failure or non-JSON output means NOT safe.
        """
        if not self.available:
            return False
        client = self._get_client()
        try:
            text = retry_transient(
                lambda: self._generate(
                    client,
                    [
                        {"role": "system", "content": _CLASSIFY_SYSTEM},
                        {"role": "user", "content": query[:2000]},
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                ),
                max_retries=self.max_retries,
                timeout_seconds=self.timeout_seconds,
                backoff_seconds=self.backoff_seconds,
                retryable=is_retryable_llm_error,
            )
            parsed = json.loads(text.strip())
            return bool(parsed.get("safe", False))
        except Exception:
            return False
