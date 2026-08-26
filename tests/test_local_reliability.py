"""Regression tests for honest local Ollama readiness and stream cancellation."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

import pytest
from fastapi import HTTPException

import webhook_server
from app.config import Settings
from app.llm.local_llm import LocalLLM
from app.llm.mock_llm import MockLLM
from app.pipeline import _build_llm, make_llm


class _ModelsResponse:
    def __init__(self, names: list[str], status_code: int = 200):
        self.status_code = status_code
        self._names = names

    def json(self):
        return {"data": [{"id": name} for name in self._names]}


def test_local_llm_readiness_requires_the_configured_model(monkeypatch):
    llm = LocalLLM(model="qwen2.5:3b-instruct-q4_k_m")
    monkeypatch.setattr(
        "requests.get", lambda *_args, **_kwargs: _ModelsResponse(["other-model"])
    )

    status = llm.readiness(force=True)

    assert status["ready"] is False
    assert status["code"] == "model_missing"
    assert llm.available is False


def test_local_llm_readiness_reports_ready_only_for_installed_model(monkeypatch):
    llm = LocalLLM(model="qwen2.5:3b-instruct-q4_k_m")
    monkeypatch.setattr(
        "requests.get",
        lambda *_args, **_kwargs: _ModelsResponse(["qwen2.5:3b-instruct-q4_k_m"]),
    )

    assert llm.readiness(force=True)["ready"] is True


def test_local_backend_never_silently_turns_into_mock_when_ollama_is_down(monkeypatch):
    monkeypatch.setattr(LocalLLM, "available", property(lambda _self: False))
    local = _build_llm(
        replace(Settings(), app_mode="local", llm_backend="local"), "local"
    )

    assert isinstance(local, LocalLLM)
    assert not isinstance(local, MockLLM)

    with_configured_fallback = make_llm(
        replace(Settings(), app_mode="local", llm_backend="local", llm_fallback_backend="mock")
    )
    assert isinstance(with_configured_fallback, LocalLLM)


def test_health_exposes_recoverable_local_llm_state(monkeypatch):
    monkeypatch.setattr(
        webhook_server,
        "_local_llm_status",
        lambda: {"ready": False, "code": "model_missing", "detail": "Model is missing."},
    )

    payload = asyncio.run(webhook_server.health())

    assert payload["status"] == "degraded"
    assert payload["llm_ready"] is False
    assert payload["llm_code"] == "model_missing"


def test_cancelled_local_request_does_not_start_pipeline_work():
    event = threading.Event()
    event.set()
    body = webhook_server.ChatRequest(session_id="cancelled-session", text="Xin chào")

    with pytest.raises(HTTPException) as exc_info:
        webhook_server._local_chat_payload(body, object(), event)

    assert exc_info.value.status_code == 499


def test_local_ui_aborts_old_stream_before_starting_a_new_one():
    source = (webhook_server.Path(webhook_server.ROOT) / "web" / "index.html").read_text(encoding="utf-8")

    assert "activeChatAbort.abort()" in source
    assert "signal:chatAbort.signal" in source
