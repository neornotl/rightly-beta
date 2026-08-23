"""Regression tests for the lightweight Vercel chat handler."""

from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from api import index


class _Response:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def _post_handler(path: str, payload: dict):
    request = object.__new__(index.handler)
    request.path = path
    raw = json.dumps(payload).encode("utf-8")
    request.headers = {"Content-Length": str(len(raw))}
    request.rfile = BytesIO(raw)
    sent = {}
    request._send = lambda status, content_type, body: sent.update(
        status=status, content_type=content_type, body=body
    )
    return request, sent


def _raw_post_handler(path: str, body: bytes, content_type: str = "application/octet-stream"):
    request = object.__new__(index.handler)
    request.path = path
    request.headers = {"Content-Length": str(len(body)), "Content-Type": content_type}
    request.rfile = BytesIO(body)
    sent = {}
    request._send = lambda status, content_type, response_body: sent.update(
        status=status, content_type=content_type, body=response_body
    )
    return request, sent


def test_vercel_handler_uses_configured_primary_provider(monkeypatch):
    monkeypatch.setattr(index, "GROQ_KEY", "test-groq-key")
    monkeypatch.setattr(index, "PATEWAY_KEY", None)
    monkeypatch.setattr(
        index,
        "urlopen",
        lambda *_args, **_kwargs: _Response({"choices": [{"message": {"content": "LLM answer"}}]}),
    )

    assert index.handler._ask_api("Xin chào", "vi") == "LLM answer"


def test_vercel_handler_requires_clarification_for_broad_age_benefit_question(monkeypatch):
    monkeypatch.setattr(index, "GROQ_KEY", "test-groq-key")
    monkeypatch.setattr(index, "PATEWAY_KEY", None)
    captured = {}

    def capture_request(request, **_kwargs):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"choices": [{"message": {"content": "Dạ, bác quan tâm mảng nào ạ?"}}]})

    monkeypatch.setattr(index, "urlopen", capture_request)

    index.handler._ask_api("Tôi năm nay 70 tuổi thì có những quyền lợi gì?", "vi")

    system_prompt = captured["messages"][0]["content"]
    assert "CÂU HỎI QUÁ RỘNG" in system_prompt
    assert "KHÔNG được tự liệt kê" in system_prompt
    assert "Chỉ hỏi lại đúng MỘT câu" in system_prompt
    assert "Markdown chi tiết vừa phải" in system_prompt


def test_vercel_handler_passes_recent_history_to_the_llm(monkeypatch):
    monkeypatch.setattr(index, "GROQ_KEY", "test-groq-key")
    monkeypatch.setattr(index, "PATEWAY_KEY", None)
    captured = {}

    def capture_request(request, **_kwargs):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"choices": [{"message": {"content": "BHYT answer"}}]})

    monkeypatch.setattr(index, "urlopen", capture_request)
    history = [
        {"role": "user", "content": "Tôi 70 tuổi có quyền lợi gì?"},
        {"role": "assistant", "content": "Bác muốn hỏi mảng nào?"},
    ]

    index.handler._ask_api("BHYT", "vi", history)

    assert captured["messages"][1:3] == history
    assert captured["messages"][-1] == {"role": "user", "content": "BHYT"}


def test_vercel_handler_transcribes_raw_browser_audio_without_json_parsing(monkeypatch):
    monkeypatch.setattr(index, "GROQ_KEY", "test-groq-key")
    captured = {}

    def capture_request(request, **_kwargs):
        captured["url"] = request.full_url
        captured["body"] = request.data
        return _Response({"text": "Tôi cần hỏi về BHYT"})

    monkeypatch.setattr(index, "urlopen", capture_request)
    request, sent = _raw_post_handler("/api/voice/transcribe?ext=.webm", b"fake-webm-audio", "audio/webm")

    request.do_POST()

    assert sent["status"] == 200
    assert json.loads(sent["body"]) == {"transcript": "Tôi cần hỏi về BHYT"}
    assert captured["url"].endswith("/audio/transcriptions")
    assert b"whisper-large-v3-turbo" in captured["body"]
    assert b"fake-webm-audio" in captured["body"]


def test_vercel_handler_never_substitutes_canned_answer_when_providers_fail(monkeypatch):
    monkeypatch.setattr(index, "GEMINI_KEY", "")
    monkeypatch.setattr(index, "GROQ_KEY", "test-groq-key")
    monkeypatch.setattr(index, "PATEWAY_KEY", "test-pateway-key")

    def fail(*_args, **_kwargs):
        raise HTTPError("https://provider.invalid", 401, "Unauthorized", {}, BytesIO())

    monkeypatch.setattr(index, "urlopen", fail)

    with pytest.raises(index.LLMUnavailableError) as exc_info:
        index.handler._ask_api("Viết một câu thơ", "vi")

    assert exc_info.value.failures == [
        {"provider": "gemini", "code": "not_configured"},
        {"provider": "groq", "code": "http_401"},
        {"provider": "pateway", "code": "http_401"},
    ]


def test_vercel_chat_returns_503_instead_of_a_canned_answer_when_llm_fails(monkeypatch):
    monkeypatch.setattr(index, "GROQ_KEY", "test-groq-key")
    monkeypatch.setattr(index, "PATEWAY_KEY", None)
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args: (_ for _ in ()).throw(
        index.LLMUnavailableError([{"provider": "groq", "code": "http_401"}])
    ))
    request, sent = _post_handler("/api/chat/stream", {"text": "Viết một câu thơ"})

    request.do_POST()

    assert sent["status"] == 503
    body = json.loads(sent["body"])
    assert body["code"] == "LLM_UNAVAILABLE"
    assert "liên hệ cơ quan" not in body["detail"]


def test_vercel_tries_pateway_when_groq_fails(monkeypatch):
    monkeypatch.setattr(index, "GEMINI_KEY", "")
    monkeypatch.setattr(index, "GROQ_KEY", "test-groq-key")
    monkeypatch.setattr(index, "PATEWAY_KEY", "test-pateway-key")
    calls = []

    def call_provider(request, **_kwargs):
        calls.append(request.full_url)
        if "groq" in request.full_url:
            raise HTTPError(request.full_url, 429, "Too Many Requests", {}, BytesIO())
        return _Response({"choices": [{"message": {"content": "Pateway answer"}}]})

    monkeypatch.setattr(index, "urlopen", call_provider)

    assert index.handler._ask_api("Xin chào", "vi") == "Pateway answer"
    assert len(calls) == 2


def test_vercel_tries_gemini_first_when_configured(monkeypatch):
    monkeypatch.setattr(index, "GEMINI_KEY", "AQ.test-express-key")
    monkeypatch.setattr(index, "GROQ_KEY", "test-groq-key")
    monkeypatch.setattr(index, "PATEWAY_KEY", None)
    calls = []

    def call_provider(request, **_kwargs):
        calls.append(request.full_url)
        if "aiplatform.googleapis.com" in request.full_url:
            payload = {
                "candidates": [
                    {"content": {"parts": [{"text": '{"answer_text": "Gemini answer"}'}]}}
                ]
            }
            return _Response(payload)
        return _Response({"choices": [{"message": {"content": "Groq answer"}}]})

    monkeypatch.setattr(index, "urlopen", call_provider)

    assert index.handler._ask_api("Xin chào", "vi") == "Gemini answer"
    assert len(calls) == 1
    assert "gemini-2.5-flash" in calls[0]


def test_vercel_rate_limit_blocks_after_cap(monkeypatch):
    monkeypatch.setattr(index, "RATE_LIMIT_PER_IP", 2)
    monkeypatch.setattr(index, "RATE_LIMIT_WARN_AT", 0.8)
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args, **_kw: "ok")
    index._RL_HITS.clear()
    statuses = []
    sent429 = None
    for i in range(3):
        request, sent = _post_handler("/api/chat", {"text": "xin chào"})
        request.do_POST()
        statuses.append(sent["status"])
        if sent["status"] == 429:
            sent429 = sent
    assert statuses == [200, 200, 429]
    assert "vượt số lượt" in json.loads(sent429["body"])["detail"]


def test_vercel_handler_has_no_embedded_provider_key():
    source = (index.ROOT / "api" / "index.py").read_text(encoding="utf-8")
    assert 'or "sk-' not in source
    assert "b64decode" not in source
