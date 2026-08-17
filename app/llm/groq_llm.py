"""Groq LLM adapter (optional, lazy import of groq SDK)."""

from __future__ import annotations

import json

from app.llm.base import BaseLLM, LLMError, format_history, is_retryable_llm_error, retry_transient
from app.llm.prompts import CLASSIFY_SYSTEM, SYSTEM_PROMPT
from app.schemas import RetrievedChunk

_SYSTEM = SYSTEM_PROMPT
_CLASSIFY_SYSTEM = CLASSIFY_SYSTEM


class GroqLLM(BaseLLM):
    name = "groq"

    def __init__(
        self,
        api_key: str = "",
        model: str = "llama-3.1-8b-instant",
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        api_keys: tuple[str, ...] = (),
    ):
        # F4: key rotation. `api_key` stays for backward compatibility and is
        # used as the primary when `api_keys` is empty. Rotation order matters:
        # the first working key keeps working, 429/5xx rotates to the next.
        self.api_keys = tuple(api_keys) if api_keys else tuple(k for k in (api_key,) if k)
        self.api_key = self.api_keys[0] if self.api_keys else api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._client = None
        self._key_index = 0
        self.last_usage: dict = {}  # R25: token/cost tracking for 10k eval

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq  # type: ignore

                self._client = Groq(
                    api_key=self.api_keys[self._key_index],
                    timeout=self.timeout_seconds,
                )
            except ImportError as exc:
                raise LLMError(
                    "groq not installed. pip install -r requirements-optional.txt"
                ) from exc
            except Exception as exc:
                raise LLMError(f"Failed to init Groq client: {exc}") from exc
        return self._client

    def _rotate(self) -> bool:
        """Move to the next key; False when already on the last one."""
        if self._key_index >= len(self.api_keys) - 1:
            return False
        self._key_index += 1
        self._client = None
        return True

    def _call_with_rotation(self, fn, retryable=is_retryable_llm_error) -> dict:
        """Retry within a key, then rotate on retryable errors across keys."""
        while True:
            try:
                return retry_transient(
                    lambda: fn(self._get_client()),
                    max_retries=self.max_retries,
                    timeout_seconds=self.timeout_seconds,
                    backoff_seconds=self.backoff_seconds,
                    retryable=retryable,
                )
            except Exception as exc:
                # Non-retryable (e.g. non-JSON) fails the same on every key.
                if not retryable(exc):
                    raise
                if not self._rotate():
                    raise
                print(
                    f"  [GroqLLM] key {self._key_index} active after: {type(exc).__name__}: {exc}"
                )

    def generate_answer(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        max_chars: int = 2000,
        history: Optional[list[dict]] = None,
    ) -> dict:
        if not self.available:
            raise LLMError("GROQ_API_KEY is not set (LLM_BACKEND=groq).")
        context = "\n\n".join(
            f"[source_id={c.source_id}|chunk_id={c.chunk_id}]\n{c.text}" for c in chunks
        )
        history_block = format_history(history)
        user = (
            (f"{history_block}\n\n" if history_block else "")
            + f"Câu hỏi: {query}\n\n"
            f"Các đoạn nguồn (chỉ được dùng các source_id này):\n{context}\n\n"
            f"Giới hạn câu trả lời: {max_chars} ký tự.\n\n"
            "Trả lời theo đúng JSON sau, không thêm chú thích ngoài JSON:\n"
            '{"answer_text": "...", "spoken_citation": "...", '
            '"source_ids": ["source_id đã dùng"], "limitations": ["..."], '
            '"next_step": "..."}'
        )
        try:
            completion = self._call_with_rotation(
                lambda client: client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
            )
        except Exception as exc:
            raise LLMError(f"Groq request failed after retries: {exc}") from exc
        self.last_usage = {
            "model": getattr(completion, "model", ""),
            "prompt_tokens": int(getattr(completion.usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(completion.usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(completion.usage, "total_tokens", 0) or 0),
        }
        text = completion.choices[0].message.content.strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            # Not retryable: a fresh call fails the same way (F/T3 fix).
            raise LLMError(f"Groq returned non-JSON output: {exc}") from exc
        parsed.setdefault("source_ids", [])
        parsed.setdefault("limitations", [])
        parsed.setdefault("next_step", "")
        chunk_to_source = {c.chunk_id: c.source_id for c in chunks}
        mapped = [chunk_to_source.get(sid, sid) for sid in parsed.get("source_ids", [])]
        parsed["source_ids"] = mapped
        # NOTE: raw source_ids are deliberately NOT filtered here (F2 fix).
        # The pipeline runs CitationValidator on the raw list so hallucinated
        # citations can be detected, then sanitizes afterwards.
        return parsed

    def classify_safe(self, query: str, chunks: list[RetrievedChunk]) -> bool:
        """LLM-based safety classification (router step 7, cloud mode only).

        Conservative: any failure or non-JSON output means NOT safe.
        """
        if not self.available:
            return False
        try:
            completion = self._call_with_rotation(
                lambda client: client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _CLASSIFY_SYSTEM},
                        {"role": "user", "content": query[:2000]},
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
            )
            parsed = json.loads(completion.choices[0].message.content.strip())
            return bool(parsed.get("safe", False))
        except Exception:
            return False
