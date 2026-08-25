"""The desktop launcher must not open a UI for a degraded local LLM."""

from __future__ import annotations

import json

import rightly_desktop


class _HealthResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def test_desktop_launcher_requires_ready_health_contract(monkeypatch):
    monkeypatch.setattr(
        rightly_desktop.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _HealthResponse({"status": "ok", "llm_ready": True}),
    )

    assert rightly_desktop._health()


def test_desktop_launcher_rejects_degraded_or_incomplete_health(monkeypatch):
    monkeypatch.setattr(
        rightly_desktop.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _HealthResponse({"status": "degraded", "llm_ready": False}),
    )
    assert not rightly_desktop._health()

    monkeypatch.setattr(
        rightly_desktop.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _HealthResponse({"status": "ok"}),
    )
    assert not rightly_desktop._health()


def test_batch_launcher_checks_json_status_and_llm_readiness():
    source = (rightly_desktop.Path(__file__).resolve().parents[1] / "Rightly.bat").read_text(encoding="utf-8")

    assert "Invoke-RestMethod" in source
    assert "$state.status -eq 'ok'" in source
    assert "$state.llm_ready -eq $true" in source
