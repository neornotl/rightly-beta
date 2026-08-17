"""GATE 5 — Privacy, consent & auditability (Luna gate #5).

Fake-PII run through the real offline pipeline must not leak into logs;
raw audio must be deleted even when the pipeline fails mid-way; and a
session must be traceable (and deletable) by session_id without storing a
real identity.

The same run must be repeated against a REAL deployment with a kill-app
mid-session test before opening the pilot (manual ops gate 8).
"""

from __future__ import annotations

import json

from app.pipeline import Pipeline
from app.privacy.scrubber import scrub_outbound
from app.safety.policy import Policy
from app.safety.router import SafetyRouter
from app.validation.citation_validator import CitationValidator

FAKE_PII = (
    "Tôi tên Nguyễn Văn A, CCCD 079203001234, số điện thoại 0987654321, "
    "email nguyenvana@gmail.com, ở số 12 đường Nguyễn Huệ, xã Bình Minh. "
    "Tôi muốn hỏi thủ tục cấp hộ khẩu?"
)


def _records(pipeline: Pipeline) -> str:
    return json.dumps(pipeline.store.logger.read_records(), ensure_ascii=False)


def test_gate5_pii_not_in_logs_by_default(offline_pipeline):
    session_id = offline_pipeline.create_session()
    offline_pipeline.process_text(session_id, FAKE_PII)
    text = _records(offline_pipeline)
    for leak in ("079203001234", "0987654321", "nguyenvana@gmail.com", "Nguyễn Văn A"):
        assert leak not in text, f"PII leaked into logs: {leak}"
    offline_pipeline.delete_session(session_id)


def test_gate5_outbound_scrubber_redacts_pii():
    scrubbed = scrub_outbound(FAKE_PII)
    assert "[CCCD]" in scrubbed
    assert "[SĐT]" in scrubbed
    assert "[EMAIL]" in scrubbed
    for leak in ("079203001234", "0987654321", "nguyenvana@gmail.com"):
        assert leak not in scrubbed


def test_gate5_no_api_key_in_logs(tmp_path, bm25_retriever):
    from app.faq import FAQMatcher
    from app.llm.mock_llm import MockLLM
    from app.tts.mock_tts import MockTTS
    from tests.gates.conftest import make_settings

    settings = make_settings(tmp_path, pateway_api_key="FAKE_KEY_FOR_GATE5")
    pipeline = Pipeline(
        settings=settings,
        retriever=bm25_retriever,
        llm=MockLLM(),
        tts=MockTTS(),
        router=SafetyRouter(settings=settings, policy=Policy()),
        validator=CitationValidator("data/law_status.json"),
        faq=FAQMatcher(),
    )
    session_id = pipeline.create_session()
    pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu?")
    text = (pipeline.store.logger.path).read_text(encoding="utf-8")
    assert "FAKE_KEY_FOR_GATE5" not in text
    pipeline.delete_session(session_id)


def test_gate5_audio_deleted_even_when_asr_fails(offline_pipeline, monkeypatch):
    audio = offline_pipeline.settings.resolved_data_dir() / "audio" / "broken.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"RIFF fake wav")

    class Boom:
        name = "boom"

        def transcribe(self, path):
            raise RuntimeError("asr exploded")

    monkeypatch.setattr(offline_pipeline, "asr", Boom())
    session_id = offline_pipeline.create_session()
    try:
        offline_pipeline.process_audio(session_id, audio)
    except RuntimeError:
        pass
    assert not audio.exists(), "raw audio must be deleted even on ASR failure"
    offline_pipeline.delete_session(session_id)


def test_gate5_session_traceable_and_deletable(offline_pipeline):
    session_id = offline_pipeline.create_session()
    offline_pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu?")
    before = len(offline_pipeline.store.logger.read_records())
    removed = offline_pipeline.delete_session(session_id)
    assert removed > 0
    assert all(r.get("session_id") != session_id for r in offline_pipeline.store.logger.read_records())
    assert len(offline_pipeline.store.logger.read_records()) < before
