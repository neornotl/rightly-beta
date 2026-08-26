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
    request._send = lambda status, content_type, body, **kwargs: sent.update(
        status=status, content_type=content_type, body=body, **kwargs
    )
    return request, sent


def _raw_post_handler(path: str, body: bytes, content_type: str = "application/octet-stream"):
    request = object.__new__(index.handler)
    request.path = path
    request.headers = {"Content-Length": str(len(body)), "Content-Type": content_type}
    request.rfile = BytesIO(body)
    sent = {}
    request._send = lambda status, content_type, response_body, **kwargs: sent.update(
        status=status, content_type=content_type, body=response_body, **kwargs
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


def _assert_cloud_payload_is_scrubbed(payload: dict) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    for secret in (
        "pilot.user@example.test",
        "0900 123 456",
        "012345678901",
        "số 12 đường Hoa Mai",
    ):
        assert secret not in serialized
    assert "[EMAIL]" in serialized
    assert "[SĐT]" in serialized
    assert "[CCCD]" in serialized
    assert "[ĐỊA CHỈ]" in serialized


def test_vercel_handler_scrubs_pii_before_sending_to_groq(monkeypatch):
    monkeypatch.setattr(index, "GEMINI_KEY", "")
    monkeypatch.setattr(index, "GROQ_KEY", "test-groq-key")
    monkeypatch.setattr(index, "PATEWAY_KEY", "")
    captured = {}

    def capture_request(request, **_kwargs):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(index, "urlopen", capture_request)
    index.handler._ask_api(
        "Email pilot.user@example.test, gọi 0900 123 456; CCCD 012345678901; ở số 12 đường Hoa Mai.",
        "vi",
        [{"role": "assistant", "content": "Hồ sơ trước: pilot.user@example.test"}],
    )

    _assert_cloud_payload_is_scrubbed(captured)


def test_vercel_handler_scrubs_pii_before_sending_to_gemini(monkeypatch):
    monkeypatch.setattr(index, "GEMINI_KEY", "AQ.test-express-key")
    monkeypatch.setattr(index, "GROQ_KEY", "")
    monkeypatch.setattr(index, "PATEWAY_KEY", "")
    captured = {}

    def capture_request(request, **_kwargs):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"candidates": [{"content": {"parts": [{"text": '{"answer_text":"ok"}'}]}}]})

    monkeypatch.setattr(index, "urlopen", capture_request)
    index.handler._ask_api(
        "Email pilot.user@example.test, gọi 0900 123 456; CCCD 012345678901; ở số 12 đường Hoa Mai.",
        "vi",
        [{"role": "user", "content": "Hồ sơ trước: pilot.user@example.test"}],
    )

    _assert_cloud_payload_is_scrubbed(captured)


def test_vercel_handler_scrubs_pii_before_sending_to_pateway(monkeypatch):
    monkeypatch.setattr(index, "GEMINI_KEY", "")
    monkeypatch.setattr(index, "GROQ_KEY", "")
    monkeypatch.setattr(index, "PATEWAY_KEY", "test-pateway-key")
    captured = {}

    def capture_request(request, **_kwargs):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(index, "urlopen", capture_request)
    index.handler._ask_api(
        "Email pilot.user@example.test, gọi 0900 123 456; CCCD 012345678901; ở số 12 đường Hoa Mai.",
        "vi",
        [{"role": "assistant", "content": "Hồ sơ trước: pilot.user@example.test"}],
    )

    _assert_cloud_payload_is_scrubbed(captured)


def test_handler_keeps_raw_turn_for_local_retrieval_before_cloud_boundary(monkeypatch):
    raw_question = "Tôi ở số 12 đường Hoa Mai, CCCD 012345678901 cần hỏi BHYT"
    captured = {}
    monkeypatch.setattr(index, "RATE_LIMIT_PER_IP", 99)
    monkeypatch.setattr(index, "RATE_LIMIT_WARN_AT", 2)
    monkeypatch.setattr(index, "_grounded_search", lambda text, **_kw: captured.setdefault("rag", text) and [])
    monkeypatch.setattr(
        index.handler,
        "_ask_api",
        lambda _self, text, _lang, history=None, **_kw: captured.update(text=text, history=history) or "ok",
    )
    request, sent = _post_handler(
        "/api/chat",
        {"text": raw_question, "history": [{"role": "user", "content": raw_question}]},
    )

    request.do_POST()

    assert sent["status"] == 200
    assert captured["rag"] == raw_question
    assert captured["text"] == raw_question
    assert captured["history"] == [{"role": "user", "content": raw_question}]


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


@pytest.mark.parametrize(
    ("headers", "expected_key", "expected_source"),
    [
        ({"x-vercel-forwarded-for": "203.0.113.7"}, "203.0.113.7", "vercel_forwarded"),
        ({"x-real-ip": "2001:db8::7"}, "2001:db8::7", "real_ip"),
        ({"x-forwarded-for": "not-an-ip, 198.51.100.8"}, "198.51.100.8", "forwarded"),
        ({"x-vercel-forwarded-for": "not-an-ip", "x-real-ip": "also-bad"}, "anon", "missing"),
    ],
)
def test_rate_limit_key_uses_valid_platform_ip_without_logging_it(headers, expected_key, expected_source):
    key, source = index._rate_limit_key(headers)
    assert (key, source) == (expected_key, expected_source)


def test_rate_limit_buckets_are_independent_and_429_has_retry_after(monkeypatch):
    monkeypatch.setattr(index, "RATE_LIMIT_PER_IP", 1)
    index._RL_HITS.clear()
    assert index._rate_check("203.0.113.1")[0]
    assert not index._rate_check("203.0.113.1")[0]
    assert index._rate_check("203.0.113.2")[0]

    request, sent = _post_handler("/api/chat", {"text": "xin chào"})
    request.headers["x-vercel-forwarded-for"] = "203.0.113.3"
    index._RL_HITS["203.0.113.3"] = [__import__("time").monotonic()]
    request.do_POST()
    assert sent["status"] == 429
    assert sent["retry_after"] == 3600


def test_vercel_handler_has_no_embedded_provider_key():
    source = (index.ROOT / "api" / "index.py").read_text(encoding="utf-8")
    assert 'or "sk-' not in source
    assert "b64decode" not in source


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("1+4-3+7=?", "Kết quả là 9."),
        ("(12 - 2) / 5", "Kết quả là 2."),
    ],
)
def test_basic_arithmetic_is_deterministic_and_does_not_need_a_legal_llm(question, expected):
    assert index._basic_math_reply(question, "vi") == expected
    assert index._basic_math_reply("__import__('os')", "vi") is None


@pytest.mark.parametrize(
    "question",
    [
        "quy định khi vượt đèn đỏ",
        "quy dinh khi vuot den do",
        "quy dinh khi vuot dden do",
    ],
)
def test_generic_red_light_question_is_recognised_and_requests_vehicle_type(question):
    direct = index._direct_public_reply(question, "vi")

    assert direct is not None
    reply, sources = direct
    assert "loại phương tiện" in reply
    assert "không có dữ liệu" not in reply
    assert sources == ["Nghị định 168/2024/NĐ-CP"]


def test_red_light_retrieval_keeps_motorcycle_clause_scoped_to_motorcycles():
    motorcycle = index._grounded_search("quy dinh khi vuot den do xe may")
    car = index._grounded_search("quy dinh khi vuot den do o to")

    assert [hit["cid"] for hit in motorcycle] == ["nd168_2024::c060"]
    assert "nd168_2024::c060" not in [hit["cid"] for hit in car]


def test_chat_direct_answers_skip_provider_and_never_return_raw_json(monkeypatch):
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args, **_kwargs: pytest.fail("provider should not run"))
    request, sent = _post_handler("/api/chat", {"text": "1+4-3+7=?", "lang": "vi"})

    request.do_POST()

    body = json.loads(sent["body"])
    assert sent["status"] == 200
    assert body == {"reply": "Kết quả là 9.", "sources": ["Tính toán cơ bản"], "lang": "vi"}


def test_stream_direct_answer_delta_join_equals_final_answer(monkeypatch):
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args, **_kwargs: pytest.fail("provider should not run"))
    request, sent = _post_handler("/api/chat/stream", {"text": "quy dinh khi vuot den do", "lang": "vi"})

    request.do_POST()

    events = [
        json.loads(line.removeprefix("data: "))
        for line in sent["body"].splitlines()
        if line.startswith("data: ")
    ]
    delta_text = "".join(event["text"] for event in events if event["type"] == "delta")
    final = next(event for event in events if event["type"] == "answer")
    assert sent["status"] == 200
    assert delta_text == final["reply"]
    assert "loại phương tiện" in final["reply"]


def test_weather_is_explicitly_out_of_scope_not_random_legal_guidance():
    reply, sources = index._direct_public_reply("thoi tiet hom nay", "vi")

    assert "pháp luật" in reply
    assert sources == ["Phạm vi hỗ trợ của Rightly"]
