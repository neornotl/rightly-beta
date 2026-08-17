"""Local LLM (Ollama) adapter tests: JSON parsing, retry, conservative classify."""

from __future__ import annotations

import json

import pytest

from app.llm.base import LLMError
from app.llm.local_llm import LocalLLM
from app.schemas import RetrievedChunk

CHUNKS = [RetrievedChunk(source_id="ho_tich", chunk_id="ht-1", text="ná»™i dung", score=0.9)]


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class _FakeLocalCompletion:
    def __init__(self, content: str):
        self.choices = [type("Ch", (), {"message": type("M", (), {"content": content})})]
        self.usage = _FakeUsage()


def _fake_client(completion):
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


def test_local_llm_defaults():
    llm = LocalLLM()
    assert llm.name == "local"
    assert llm.base_url == "http://localhost:11434/v1"
    assert llm.model == "qwen2.5:7b-instruct-q4_k_m"


def test_local_generate_answer_ok(monkeypatch):
    llm = LocalLLM(backoff_seconds=0)
    payload = {
        "answer_text": "tráº£ lá»i",
        "spoken_citation": "c",
        "source_ids": ["ht-1"],
        "limitations": [],
        "next_step": "",
    }
    monkeypatch.setattr(LocalLLM, "available", property(lambda self: True))
    monkeypatch.setattr(
        llm, "_get_client", lambda: _fake_client(_FakeLocalCompletion(json.dumps(payload)))
    )
    out = llm.generate_answer("há»i gÃ¬?", CHUNKS)
    assert out["answer_text"] == "tráº£ lá»i"
    assert out["source_ids"] == ["ho_tich"]  # chunk_id ht-1 mapped to its source


def test_local_generate_answer_retries_transient_then_succeeds(monkeypatch):
    llm = LocalLLM(backoff_seconds=0)
    payload = {
        "answer_text": "ok",
        "spoken_citation": "c",
        "source_ids": ["ht-1"],
        "limitations": [],
        "next_step": "",
    }
    calls = {"n": 0}

    def fake_create(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("503 Service Unavailable")
        return _FakeLocalCompletion(json.dumps(payload))

    monkeypatch.setattr(LocalLLM, "available", property(lambda self: True))
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
    out = llm.generate_answer("há»i gÃ¬?", CHUNKS)
    assert out["answer_text"] == "ok"
    assert calls["n"] == 2


def test_local_generate_answer_non_json_raises_without_retry(monkeypatch):
    llm = LocalLLM(backoff_seconds=0)
    calls = {"n": 0}

    def fake_create(self, **kwargs):
        calls["n"] += 1
        return _FakeLocalCompletion("khÃ´ng pháº£i json")

    monkeypatch.setattr(LocalLLM, "available", property(lambda self: True))
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
        llm.generate_answer("há»i gÃ¬?", CHUNKS)
    assert calls["n"] == 1


def test_local_generate_answer_unavailable_raises(monkeypatch):
    llm = LocalLLM()
    monkeypatch.setattr(LocalLLM, "available", property(lambda self: False))
    with pytest.raises(LLMError, match="unreachable"):
        llm.generate_answer("há»i gÃ¬?", CHUNKS)


def test_local_classify_safe_true(monkeypatch):
    llm = LocalLLM(backoff_seconds=0)
    monkeypatch.setattr(LocalLLM, "available", property(lambda self: True))
    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: _fake_client(_FakeLocalCompletion(json.dumps({"safe": True}))),
    )
    assert llm.classify_safe("cÃ¢u há»i?", CHUNKS) is True


def test_local_classify_safe_conservative_on_failure(monkeypatch):
    llm = LocalLLM(backoff_seconds=0)

    def fake_create(self, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(LocalLLM, "available", property(lambda self: True))
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
    assert llm.classify_safe("cÃ¢u há»i?", CHUNKS) is False

