"""T3 tests: production-grade cloud LLM (timeout, retry, classify_safe)."""

from __future__ import annotations

import json

import pytest

from app.llm.base import LLMError, is_retryable_llm_error, retry_transient
from app.llm.gemini_llm import GeminiLLM
from app.llm.groq_llm import GroqLLM
from app.llm.pateway_llm import PatewayLLM
from app.schemas import RetrievedChunk

CHUNKS = [RetrievedChunk(source_id="ho_tich", chunk_id="ht-1", text="nội dung", score=0.9)]


def test_is_retryable_llm_error_network_and_5xx():
    assert is_retryable_llm_error(ConnectionError("connection reset"))
    assert is_retryable_llm_error(TimeoutError("timed out"))
    assert is_retryable_llm_error(RuntimeError("429 Too Many Requests"))
    assert is_retryable_llm_error(RuntimeError("503 Service Unavailable"))
    assert not is_retryable_llm_error(RuntimeError("400 Bad Request"))
    assert not is_retryable_llm_error(LLMError("non-JSON output"))


def test_retry_transient_succeeds_after_retries(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("flaky")
        return "ok"

    assert retry_transient(flaky, max_retries=3, backoff_seconds=0) == "ok"
    assert calls["n"] == 3


def test_retry_transient_gives_up_after_max(monkeypatch):
    def always_fail():
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        retry_transient(always_fail, max_retries=2, backoff_seconds=0)


def test_retry_transient_does_not_retry_non_retryable():
    def fail():
        raise LLMError("400 Bad Request")

    with pytest.raises(LLMError):
        retry_transient(fail, max_retries=3, backoff_seconds=0)


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeChoices:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})


class _FakeCompletion:
    def __init__(self, content: str):
        self.choices = [_FakeChoices(content)]
        self.usage = _FakeUsage()


def test_groq_generate_answer_retries_transient_then_succeeds(monkeypatch):
    llm = GroqLLM(api_key="x", backoff_seconds=0)
    calls = {"n": 0}

    def fake_create(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("503 Service Unavailable")
        return _FakeCompletion(
            json.dumps(
                {
                    "answer_text": "ok",
                    "spoken_citation": "c",
                    "source_ids": ["ht-1"],
                    "limitations": [],
                    "next_step": "",
                }
            )
        )

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C",
            (),
            {
                "chat": type(
                    "Chat", (), {"completions": type("Comp", (), {"create": fake_create})()}
                )()
            },
        )(),
    )
    out = llm.generate_answer("hỏi gì?", CHUNKS)
    assert out["answer_text"] == "ok"
    assert calls["n"] == 2


def test_groq_generate_answer_non_json_raises_without_retry(monkeypatch):
    llm = GroqLLM(api_key="x", backoff_seconds=0)
    calls = {"n": 0}

    def fake_create(self, **kwargs):
        calls["n"] += 1
        return _FakeCompletion("không phải json")

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C",
            (),
            {
                "chat": type(
                    "Chat", (), {"completions": type("Comp", (), {"create": fake_create})()}
                )()
            },
        )(),
    )
    with pytest.raises(LLMError, match="non-JSON"):
        llm.generate_answer("hỏi gì?", CHUNKS)
    assert calls["n"] == 1


def test_groq_classify_safe_true(monkeypatch):
    llm = GroqLLM(api_key="x", backoff_seconds=0)

    def fake_create(self, **kwargs):
        return _FakeCompletion(json.dumps({"safe": True}))

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C",
            (),
            {
                "chat": type(
                    "Chat", (), {"completions": type("Comp", (), {"create": fake_create})()}
                )()
            },
        )(),
    )
    assert llm.classify_safe("thủ tục cấp sổ đỏ cần gì?", CHUNKS) is True


def test_groq_classify_safe_conservative_on_failure(monkeypatch):
    llm = GroqLLM(api_key="x", backoff_seconds=0)

    def fake_create(self, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C",
            (),
            {
                "chat": type(
                    "Chat", (), {"completions": type("Comp", (), {"create": fake_create})()}
                )()
            },
        )(),
    )
    assert llm.classify_safe("câu hỏi?", CHUNKS) is False


def test_gemini_classify_safe_true(monkeypatch):
    llm = GeminiLLM(api_key="x", backoff_seconds=0)

    def fake_generate_content(self, **kwargs):
        return _FakeResponse(json.dumps({"safe": True}))

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C", (), {"models": type("M", (), {"generate_content": fake_generate_content})()}
        )(),
    )
    assert llm.classify_safe("thủ tục khai sinh cần gì?", CHUNKS) is True


def test_gemini_classify_safe_conservative_on_non_json(monkeypatch):
    llm = GeminiLLM(api_key="x", backoff_seconds=0)

    def fake_generate_content(self, **kwargs):
        return _FakeResponse("không phải json")

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C", (), {"models": type("M", (), {"generate_content": fake_generate_content})()}
        )(),
    )
    assert llm.classify_safe("câu hỏi?", CHUNKS) is False


def test_gemini_generate_answer_retries_transient(monkeypatch):
    llm = GeminiLLM(api_key="x", backoff_seconds=0)
    calls = {"n": 0}

    def fake_generate_content(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("429 Too Many Requests")
        return _FakeResponse(
            json.dumps(
                {
                    "answer_text": "ok",
                    "spoken_citation": "c",
                    "source_ids": ["ht-1"],
                    "limitations": [],
                    "next_step": "",
                }
            )
        )

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C", (), {"models": type("M", (), {"generate_content": fake_generate_content})()}
        )(),
    )
    out = llm.generate_answer("hỏi gì?", CHUNKS)
    assert out["answer_text"] == "ok"
    assert calls["n"] == 2


# ---------- Pateway (OpenAI-compatible gateway, council R21) ----------


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class _FakePatewayCompletion:
    def __init__(self, content: str):
        self.choices = [type("Ch", (), {"message": type("M", (), {"content": content})})]
        self.usage = _FakeUsage()


def _fake_pateway_client(completion):
    return type(
        "C",
        (),
        {
            "chat": type(
                "Chat",
                (),
                {"completions": type("Comp", (), {"create": lambda self, **kw: completion})()},
            )()
        },
    )()


def test_pateway_available_only_with_key():
    assert PatewayLLM().available is False
    assert PatewayLLM(api_key="pk-x").available is True


def test_pateway_generate_answer_ok(monkeypatch):
    llm = PatewayLLM(api_key="pk-x", backoff_seconds=0)
    payload = {
        "answer_text": "trả lời",
        "spoken_citation": "c",
        "source_ids": ["ht-1"],
        "limitations": [],
        "next_step": "",
    }
    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: _fake_pateway_client(_FakePatewayCompletion(json.dumps(payload))),
    )
    out = llm.generate_answer("hỏi gì?", CHUNKS)
    assert out["answer_text"] == "trả lời"
    assert out["source_ids"] == ["ho_tich"]  # chunk_id ht-1 mapped to its source


def test_pateway_generate_answer_retries_transient_then_succeeds(monkeypatch):
    llm = PatewayLLM(api_key="pk-x", backoff_seconds=0)
    calls = {"n": 0}
    payload = {
        "answer_text": "ok",
        "spoken_citation": "c",
        "source_ids": ["ht-1"],
        "limitations": [],
        "next_step": "",
    }

    def fake_create(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("503 Service Unavailable")
        return _FakePatewayCompletion(json.dumps(payload))

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C",
            (),
            {
                "chat": type(
                    "Chat", (), {"completions": type("Comp", (), {"create": fake_create})()}
                )()
            },
        )(),
    )
    out = llm.generate_answer("hỏi gì?", CHUNKS)
    assert out["answer_text"] == "ok"
    assert calls["n"] == 2


def test_pateway_generate_answer_non_json_raises_without_retry(monkeypatch):
    llm = PatewayLLM(api_key="pk-x", backoff_seconds=0)
    calls = {"n": 0}

    def fake_create(self, **kwargs):
        calls["n"] += 1
        return _FakePatewayCompletion("không phải json")

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C",
            (),
            {
                "chat": type(
                    "Chat", (), {"completions": type("Comp", (), {"create": fake_create})()}
                )()
            },
        )(),
    )
    with pytest.raises(LLMError, match="non-JSON"):
        llm.generate_answer("hỏi gì?", CHUNKS)
    assert calls["n"] == 1


def test_pateway_generate_answer_no_key_raises():
    with pytest.raises(LLMError, match="PATEWAY_API_KEY"):
        PatewayLLM().generate_answer("hỏi gì?", CHUNKS)


def test_pateway_classify_safe_true(monkeypatch):
    llm = PatewayLLM(api_key="pk-x", backoff_seconds=0)
    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: _fake_pateway_client(_FakePatewayCompletion(json.dumps({"safe": True}))),
    )
    assert llm.classify_safe("câu hỏi?", CHUNKS) is True


def test_pateway_classify_safe_conservative_on_failure(monkeypatch):
    llm = PatewayLLM(api_key="pk-x", backoff_seconds=0)

    def fake_create(self, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: type(
            "C",
            (),
            {
                "chat": type(
                    "Chat", (), {"completions": type("Comp", (), {"create": fake_create})()}
                )()
            },
        )(),
    )
    assert llm.classify_safe("câu hỏi?", CHUNKS) is False
