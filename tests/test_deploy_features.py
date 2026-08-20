"""Tests for the one-click deploy features: legal intake, answer review,
audio-byte voice input, and the local Whisper backend wiring."""

from __future__ import annotations

from app.asr.base import BaseASR
from app.config import Settings
from app.pipeline import Pipeline, make_asr
from app.schemas import Action

from tests.test_pipeline_mock import _pipeline


def test_legal_intake_asks_one_question_before_personal_answer(tmp_path):
    pipeline = _pipeline(tmp_path, legal_intake=True)
    session_id = pipeline.create_session()

    result = pipeline.process_text(
        session_id, "Tôi muốn biết khi nào tôi được nghỉ hưu?"
    )

    assert result.decision.action == Action.CLARIFY
    assert result.answer is not None
    assert "sinh năm" in result.answer.answer_text
    assert pipeline._hybrid_sessions[session_id].pending_intake


def test_legal_intake_with_complete_facts_answers_directly(tmp_path):
    pipeline = _pipeline(tmp_path, legal_intake=True)
    session_id = pipeline.create_session()

    result = pipeline.process_text(
        session_id,
        "Tôi là nam sinh năm 1964, đóng BHXH 30 năm, khi nào được nghỉ hưu?",
    )

    assert result.decision.action == Action.ANSWER
    assert result.answer is not None
    assert pipeline._hybrid_sessions[session_id].pending_intake is None


def test_legal_intake_skipped_for_impersonal_rule_questions(tmp_path, monkeypatch):
    pipeline = _pipeline(tmp_path, legal_intake=True)
    session_id = pipeline.create_session()
    called = []

    original = pipeline.llm.generate_answer

    def spy(query, chunks, **kwargs):
        if kwargs.get("system_prompt") and "tiếp nhận hồ sơ pháp lý" in kwargs["system_prompt"]:
            called.append(1)
        return original(query, chunks, **kwargs)

    monkeypatch.setattr(pipeline.llm, "generate_answer", spy)
    result = pipeline.process_text(
        session_id, "Thủ tục cấp giấy xác nhận hộ khẩu tại xã Bình Minh?"
    )

    assert called == []
    assert result.answer is not None


def test_answer_review_adds_summary_and_fit(tmp_path):
    pipeline = _pipeline(tmp_path, answer_review=True)
    session_id = pipeline.create_session()

    result = pipeline.process_text(
        session_id, "Thủ tục cấp giấy xác nhận hộ khẩu tại xã Bình Minh?"
    )

    assert result.answer is not None
    assert result.answer.summary
    assert result.answer.appropriate is True
    records = pipeline.store.logger.read_records()
    assert any(r.get("event") == "answer_reviewed" for r in records)


def test_answer_review_self_corrects_when_unfit(tmp_path, monkeypatch):
    """Unfit answer -> the model rewrites it once -> re-review passes."""
    import json

    pipeline = _pipeline(tmp_path, answer_review=True, answer_review_max_revisions=2)
    session_id = pipeline.create_session()
    original = pipeline.llm.generate_answer
    review_calls = 0
    revise_calls = 0

    def wrapped(query, chunks, **kwargs):
        nonlocal review_calls, revise_calls
        sp = kwargs.get("system_prompt") or ""
        if "kiểm duyệt cuối cùng" in sp:
            review_calls += 1
            if review_calls == 1:
                return {"answer_text": json.dumps(
                    {"summary": "Sai trọng tâm", "appropriate": False,
                     "note": "Câu trả lời chưa trả lời câu hỏi."}, ensure_ascii=False)}
            return {"answer_text": json.dumps(
                {"summary": "Đã khớp", "appropriate": True, "note": ""}, ensure_ascii=False)}
        if "viết lại một câu trả lời" in sp:
            revise_calls += 1
            return {
                "answer_text": "Câu trả lời đã được chỉnh sửa cho đúng trọng tâm.",
                "spoken_citation": "Theo nguồn.",
                "source_ids": ["demo_binhminh_procedures"],
                "limitations": [],
                "next_step": "",
            }
        return original(query, chunks, **kwargs)

    monkeypatch.setattr(pipeline.llm, "generate_answer", wrapped)
    result = pipeline.process_text(
        session_id, "Thủ tục cấp giấy xác nhận hộ khẩu tại xã Bình Minh?"
    )

    assert revise_calls == 1
    assert review_calls == 2
    assert result.answer is not None
    assert "chỉnh sửa" in result.answer.answer_text
    assert result.answer.appropriate is True
    assert result.answer.summary == "Đã khớp"


def test_answer_review_loop_is_bounded_when_always_unfit(tmp_path, monkeypatch):
    """If the reviewer keeps rejecting, revision stops after the budget."""
    import json

    pipeline = _pipeline(tmp_path, answer_review=True, answer_review_max_revisions=2)
    session_id = pipeline.create_session()
    original = pipeline.llm.generate_answer
    review_calls = 0
    revise_calls = 0

    def wrapped(query, chunks, **kwargs):
        nonlocal review_calls, revise_calls
        sp = kwargs.get("system_prompt") or ""
        if "kiểm duyệt cuối cùng" in sp:
            review_calls += 1
            return {"answer_text": json.dumps(
                {"summary": "Chưa khớp", "appropriate": False,
                 "note": "Vẫn thiếu trọng tâm."}, ensure_ascii=False)}
        if "viết lại một câu trả lời" in sp:
            revise_calls += 1
            return {
                "answer_text": f"Bản chỉnh sửa lần {revise_calls}.",
                "spoken_citation": "Theo nguồn.",
                "source_ids": ["demo_binhminh_procedures"],
                "limitations": [],
                "next_step": "",
            }
        return original(query, chunks, **kwargs)

    monkeypatch.setattr(pipeline.llm, "generate_answer", wrapped)
    result = pipeline.process_text(
        session_id, "Thủ tục cấp giấy xác nhận hộ khẩu tại xã Bình Minh?"
    )

    assert revise_calls == 2
    assert review_calls == 3
    assert result.answer is not None
    assert result.answer.appropriate is False
    assert "lần 2" in result.answer.answer_text


def test_process_audio_bytes_transcribes_and_answers(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()

    result = pipeline.process_audio_bytes(session_id, b"RIFF fake webm", extension=".webm")

    assert result.answer is not None
    assert result.query.strip()
    assert pipeline.settings.delete_raw_audio_after_session


def test_whisper_backend_is_registered_without_loading_model(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        results_dir=tmp_path / "results",
        log_dir=tmp_path / "logs",
        asr_backend="whisper",
        whisper_model="small",
        whisper_device="auto",
    )
    asr = make_asr(settings)
    assert isinstance(asr, BaseASR)
    assert asr.name == "whisper"
    # Check availability must not require the model to be downloaded already.
    ok, reason = asr.check_availability()
    assert isinstance(ok, bool)
    assert isinstance(reason, str)


def test_invalid_asr_backend_still_rejected(monkeypatch, tmp_path):
    import pytest

    from app.config import ConfigError, load_settings

    monkeypatch.setenv("ASR_BACKEND", "nope")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(ConfigError):
        load_settings()


def test_whisper_valid_asr_backend_loads(monkeypatch, tmp_path):
    from app.config import load_settings

    monkeypatch.setenv("ASR_BACKEND", "whisper")
    monkeypatch.setenv("WHISPER_MODEL", "small")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    settings = load_settings()
    assert settings.asr_backend == "whisper"
    assert settings.whisper_model == "small"


def test_config_defaults_for_deploy_features():
    settings = Settings()
    assert settings.legal_intake is False
    assert settings.answer_review is False
    assert settings.whisper_model == "small"
    assert settings.whisper_device == "auto"