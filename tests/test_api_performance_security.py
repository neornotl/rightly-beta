from __future__ import annotations

import json
from io import BytesIO

from api import index


class _NeverRead:
    def read(self, *_args, **_kwargs):
        raise AssertionError("request body must not be read after early rejection")


def _audio_request(length: str):
    request = object.__new__(index.handler)
    request.path = "/api/voice/transcribe?ext=.webm"
    request.headers = {"Content-Length": length, "Content-Type": "audio/webm"}
    request.rfile = _NeverRead()
    sent = {}
    request._send = lambda status, content_type, body: sent.update(
        status=status, content_type=content_type, body=body
    )
    return request, sent


def test_audio_limit_rejects_before_reading_body():
    request, sent = _audio_request(str(index.MAX_AUDIO_BYTES + 1))
    request.do_POST()
    assert sent["status"] == 413
    assert "20 MB" in json.loads(sent["body"])["detail"]


def test_negative_content_length_is_rejected_before_reading_body():
    request, sent = _audio_request("-1")
    request.do_POST()
    assert sent["status"] == 400


def test_oversized_chat_json_is_rejected_before_reading_body():
    request = object.__new__(index.handler)
    request.path = "/api/chat/stream"
    request.headers = {"Content-Length": str(index.MAX_JSON_BYTES + 1)}
    request.rfile = _NeverRead()
    sent = {}
    request._send = lambda status, content_type, body: sent.update(status=status, body=body)
    request.do_POST()
    assert sent["status"] == 413
    assert "512 KiB" in json.loads(sent["body"])["detail"]


def test_normal_chat_history_remains_accepted(monkeypatch):
    request = object.__new__(index.handler)
    request.path = "/api/chat"
    payload = {"text": "BHYT", "history": [{"role": "user", "content": "Tôi 70 tuổi"}]}
    raw = json.dumps(payload, ensure_ascii=False).encode()
    request.headers = {"Content-Length": str(len(raw))}
    request.rfile = BytesIO(raw)
    sent = {}
    request._send = lambda status, content_type, body: sent.update(status=status, body=body)
    monkeypatch.setattr(index.handler, "_ask_api", lambda _self, text, lang, history: "Đã nhận lịch sử.")
    request.do_POST()
    assert sent["status"] == 200
    assert json.loads(sent["body"])["reply"] == "Đã nhận lịch sử."


def test_request_log_contains_metrics_but_no_user_content(capsys):
    request = object.__new__(index.handler)
    request.path = "/api/chat"
    request._request_started = 0
    request._request_id = "test-request"
    request._retrieval_ms = 2.5
    request._provider_ms = 8.0
    request._ttfb_ms = 3.0
    request._request_log(200)
    record = json.loads(capsys.readouterr().out)
    assert record["request_id"] == "test-request"
    assert record["route"] == "/api/chat"
    assert record["status"] == 200
    assert record["retrieval_ms"] == 2.5
    assert all(key not in record for key in ("text", "history", "token", "prompt"))


def test_one_shot_stream_emits_no_fake_deltas(monkeypatch):
    request = object.__new__(index.handler)
    request.path = "/api/chat/stream"
    request._request_started = 0
    request._request_id = "stream-test"
    sent = {}
    request._send = lambda status, content_type, body: sent.update(
        status=status, content_type=content_type, body=body
    )
    monkeypatch.setattr(index, "_grounded_search", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(index.handler, "_ask_api", lambda *_args, **_kwargs: "Câu trả lời hoàn chỉnh.")
    request._stream_chat("câu hỏi", [], "vi", None)
    events = [
        json.loads(line.removeprefix("data: "))
        for line in sent["body"].decode().splitlines()
        if line.startswith("data: ")
    ]
    assert not any(event["type"] == "delta" for event in events)
    assert next(event for event in events if event["type"] == "answer")["reply"] == "Câu trả lời hoàn chỉnh."
