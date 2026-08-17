"""Pateway LLM adapter (OpenAI-compatible gateway).

Council R21: GPT 5.6 Luna via Pateway gateway is the primary backend,
Groq is the fallback. Config-driven:
  LLM_BACKEND=pateway
  PATEWAY_API_KEY=<key>        (required, else unavailable)
  PATEWAY_BASE_URL=<url>       (default https://api.pateway.ai/v1)
  PATEWAY_MODEL=<model>        (default gpt-5.6-luna)
  LLM_FALLBACK_BACKEND=groq

Safety notes (R21):
- PII is scrubbed outbound by the pipeline before reaching this adapter.
- Timeouts/retries are shared with the rest of the stack.
- source_ids are NOT generated here; the pipeline validates citations.
"""

from __future__ import annotations

import json

from app.llm.base import BaseLLM, LLMError, format_history, is_retryable_llm_error, retry_transient
from app.llm.prompts import CLASSIFY_SYSTEM, SYSTEM_PROMPT
from app.schemas import RetrievedChunk

_SYSTEM = SYSTEM_PROMPT
_CLASSIFY_SYSTEM = CLASSIFY_SYSTEM

_DEFAULT_BASE_URL = "https://api.pateway.ai/v1"
_DEFAULT_MODEL = "gpt-5.6-luna"


class PatewayLLM(BaseLLM):
    name = "pateway"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = _DEFAULT_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ):
        self.api_key = api_key
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.model = model or _DEFAULT_MODEL
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._client = None
        self.last_usage: dict = {}  # R25: token/cost tracking for 10k eval

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI  # type: ignore

                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=self.timeout_seconds,
                    max_retries=0,  # we manage retries ourselves below
                )
            except ImportError as exc:
                raise LLMError(
                    "openai not installed. pip install -r requirements-optional.txt"
                ) from exc
            except Exception as exc:
                raise LLMError(f"Failed to init Pateway client: {exc}") from exc
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
        }
        # NOTE: gpt-5.6-luna is a reasoning model — Pateway rejects `temperature`.
        # Defaults to the gateway's deterministic setting.
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
            raise LLMError("PATEWAY_API_KEY is not set (LLM_BACKEND=pateway).")
        context = "\n\n".join(
            f"[source_id={c.source_id}|chunk_id={c.chunk_id}]\n{c.text}" for c in chunks
        )
        history_block = format_history(history)
        user = (
            f"{history_block}\n\n" if history_block else ""
        ) + (
            f"Câu hỏi: {query}\n\n"
            f"Các đoạn nguồn (chỉ được dùng các source_id này):\n{context}\n\n"
            "Ưu tiên đoạn có tiêu đề điều khoản trực tiếp trả lời câu hỏi. "
            "Nếu hỏi hồ sơ/giấy tờ thì không trả lời bằng đoạn về thời hạn hoặc tạm dừng. "
            "Nếu hỏi ai/đối tượng thì nêu đầy đủ các nhóm trong đoạn nguồn phù hợp.\n"
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
            raise LLMError(f"Pateway request failed after retries: {exc}") from exc
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            # Not retryable: a fresh call fails the same way (F/T3 fix).
            raise LLMError(f"Pateway returned non-JSON output: {exc}") from exc
        parsed.setdefault("source_ids", [])
        parsed.setdefault("limitations", [])
        parsed.setdefault("next_step", "")
        chunk_to_source = {c.chunk_id: c.source_id for c in chunks}
        mapped = [chunk_to_source.get(sid, sid) for sid in parsed.get("source_ids", [])]
        parsed["source_ids"] = mapped
        # NOTE: raw source_ids are deliberately NOT filtered here (F2 fix);
        # the pipeline runs CitationValidator on the raw list, then sanitizes.
        return parsed

    def classify_safe(self, query: str, chunks: list[RetrievedChunk]) -> bool:
        """LLM-based safety classification (router step 7).

        Enabled in cloud mode and via USE_LLM_CLASSIFIER for local+pateway.
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
