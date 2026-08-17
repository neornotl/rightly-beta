"""End-to-end mock pipeline tests: text, audio privacy, logging, deletion."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.config import Settings
from app.pipeline import Pipeline
from app.schemas import Action, Zone


def _pipeline(tmp_path, **overrides) -> Pipeline:
    settings = Settings(
        data_dir=tmp_path / "data",
        results_dir=tmp_path / "results",
        log_dir=tmp_path / "logs",
        **overrides,
    )
    settings.chunks_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_log_dir().mkdir(parents=True, exist_ok=True)
    from app.retrieval.document_loader import DocumentLoader

    records = DocumentLoader(sources_dir="data/sources", chunks_dir=settings.chunks_dir).ingest()
    out = settings.chunks_dir / "demo_chunks.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
    return Pipeline(settings=settings)


def test_mock_pipeline_end_to_end(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    result = pipeline.process_text(
        session_id, "Thủ tục cấp giấy xác nhận hộ khẩu tại xã Bình Minh?"
    )
    assert result.decision.zone == Zone.YELLOW
    assert result.decision.action == Action.ANSWER
    assert result.answer is not None
    assert result.answer.source_ids == ["demo_binhminh_procedures"]
    assert "DEMO" in result.answer.limitations[0]
    assert result.latencies_ms.get("retrieval_ms", 0) >= 0
    assert result.tts_output
    pipeline.delete_session(session_id)


def test_pipeline_safe_query_cites_demo_only(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    # No FAQ match -> must answer from demo corpus and cite it only.
    result = pipeline.process_text(session_id, "Thủ tục cấp giấy xác nhận hộ khẩu tại xã Bình Minh?")
    assert result.answer is not None
    assert set(result.answer.source_ids) == {"demo_binhminh_procedures"}


def test_pipeline_refuses_when_no_source(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    result = pipeline.process_text(session_id, "Tổng thống Mỹ tên là gì?")
    assert result.decision.action == Action.REFUSE
    assert result.answer is None


def test_pipeline_emergency_never_generates_answer(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    result = pipeline.process_text(session_id, "Tôi bị đau tim, cấp cứu giúp!")
    assert result.decision.zone == Zone.RED
    assert result.answer is None
    assert "khẩn cấp" in result.decision.user_message


def test_transcripts_not_saved_by_default(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu?")
    records = pipeline.store.logger.read_records()
    texts = json.dumps(records, ensure_ascii=False)
    assert "Thủ tục cấp hộ khẩu" not in texts


def test_transcripts_saved_when_enabled(tmp_path):
    pipeline = _pipeline(tmp_path, save_transcripts=True)
    session_id = pipeline.create_session()
    pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu?")
    records = pipeline.store.logger.read_records()
    texts = json.dumps(records, ensure_ascii=False)
    assert "Thủ tục cấp hộ khẩu" in texts


def test_delete_session_removes_lines(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu?")
    before = len(pipeline.store.logger.read_records())
    removed = pipeline.delete_session(session_id)
    assert removed > 0
    after = pipeline.store.logger.read_records()
    assert len(after) < before
    assert all(r.get("session_id") != session_id for r in after)


def test_raw_audio_deleted_after_session_when_in_data_dir(tmp_path):
    pipeline = _pipeline(tmp_path)
    audio = pipeline.settings.resolved_data_dir() / "audio" / "sample.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"RIFF fake wav")
    session_id = pipeline.create_session()
    # MockASR reads sibling .txt; create transcript sidecar.
    (audio.with_suffix(".wav.txt")).write_text("Thủ tục cấp hộ khẩu?", encoding="utf-8")
    result = pipeline.process_audio(session_id, audio)
    assert not audio.exists(), "raw audio must be deleted after session"
    assert result.answer is not None


def test_audio_kept_when_outside_data_dir(tmp_path):
    pipeline = _pipeline(tmp_path)
    outside = tmp_path / "user_audio.wav"
    outside.write_bytes(b"RIFF fake wav")
    (tmp_path / "user_audio.wav.txt").write_text("Thủ tục cấp hộ khẩu?", encoding="utf-8")
    session_id = pipeline.create_session()
    pipeline.process_audio(session_id, outside)
    assert outside.exists(), "user files outside data dir must never be deleted"


def test_logs_do_not_contain_api_key(tmp_path):
    pipeline = _pipeline(tmp_path, gemini_api_key="FAKE_GEMINI_KEY_FOR_LOGGING_TEST")
    session_id = pipeline.create_session()
    pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu?")
    logs = (pipeline.store.logger.path).read_text(encoding="utf-8")
    assert "FAKE_GEMINI_KEY_FOR_LOGGING_TEST" not in logs


def test_audio_deleted_even_when_asr_fails(tmp_path, monkeypatch):
    pipeline = _pipeline(tmp_path)
    audio = pipeline.settings.resolved_data_dir() / "audio" / "broken.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"RIFF fake wav")

    class Boom:
        name = "boom"

        def transcribe(self, path):
            raise RuntimeError("asr exploded")

    monkeypatch.setattr(pipeline, "asr", Boom())
    session_id = pipeline.create_session()
    try:
        pipeline.process_audio(session_id, audio)
        assert False, "expected ASR failure to propagate"
    except RuntimeError:
        pass
    assert not audio.exists(), "raw audio must be deleted even on ASR failure"


def test_hybrid_mode_fails_loudly_without_real_chunks(tmp_path):
    pipeline = _pipeline(tmp_path)  # demo chunks only
    pipeline.settings.chunks_dir.mkdir(parents=True, exist_ok=True)
    settings = pipeline.settings.__class__(
        app_mode="local",
        retrieval_backend="hybrid",
        data_dir=pipeline.settings.data_dir,
        results_dir=pipeline.settings.results_dir,
        log_dir=pipeline.settings.log_dir,
    )
    import pytest

    from app.pipeline import make_retriever

    with pytest.raises(RuntimeError, match="real_chunks"):
        make_retriever(settings)


def test_hallucinated_citation_rejected_by_pipeline(tmp_path):
    """F2 integration: a hallucinated source_id must be caught, not filtered."""

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        "data/law_status.json",
        tmp_path / "data" / "law_status.json",
    )
    # Corpus must be real legal chunks (demo removed from runtime).
    # nd123_2015 = Nghị định 123/2015/NĐ-CP về Hộ tịch (matches "hộ tịch" query).
    real = Path("data/chunks/real_chunks.jsonl")
    chunks_tmp = tmp_path / "data" / "chunks"
    chunks_tmp.mkdir(parents=True, exist_ok=True)
    with real.open(encoding="utf-8") as src, (chunks_tmp / "real_chunks.jsonl").open(
        "w", encoding="utf-8"
    ) as dst:
        for _ in range(2):
            line = src.readline()
            if line:
                dst.write(line)
    pipeline = _pipeline(tmp_path, app_mode="local")

    class FakeLLM:
        name = "fake"

        def generate_answer(self, query, chunks, max_chars=2000, history=None):
            # Hallucinate a source_id NOT in retrieved chunks (nd123_2015)
            return {
                "answer_text": "câu trả lời bịa",
                "spoken_citation": "",
                "source_ids": ["HALLUCINATED_SRC"],
                "limitations": [],
                "next_step": "",
            }

    pipeline.llm = FakeLLM()  # type: ignore[assignment]
    session_id = pipeline.create_session()
    # Query matching nd123_2015 (Nghị định 123/2015 về Hộ tịch)
    result = pipeline.process_text(session_id, "Nghị định 123/2015/NĐ-CP về hộ tịch quy định gì?")
    assert result.decision.action == Action.REFUSE
    assert result.decision.zone == Zone.ORANGE
    assert "CITATION_UNSUPPORTED" in result.decision.reason_codes
    assert result.answer is None


def test_ungrounded_answer_refused(tmp_path):
    """Council T2: answer with content but zero citations is refused."""
    pipeline = _pipeline(tmp_path)

    class NoCiteLLM:
        name = "nocite"

        def generate_answer(self, query, chunks, max_chars=2000, history=None):
            return {
                "answer_text": "Tôi khẳng định chắc chắn câu này đúng.",
                "spoken_citation": "",
                "source_ids": [],
                "limitations": [],
                "next_step": "",
            }

    pipeline.llm = NoCiteLLM()  # type: ignore[assignment]
    session_id = pipeline.create_session()
    result = pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu?")
    assert result.decision.action == Action.REFUSE
    assert result.answer is None
    assert "INSUFFICIENT_SOURCE" in result.decision.reason_codes


def test_followup_uses_temporary_session_memory(tmp_path):
    """Turn 2 that alone retrieves nothing must still be answered using the
    previous turn's grounded evidence (temporary session memory)."""
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()

    r1 = pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu tại xã Bình Minh?")
    assert r1.answer is not None
    assert len(pipeline._memory[session_id]) == 1

    r2 = pipeline.process_text(session_id, "vâng ạ")
    assert r2.answer is not None, "follow-up must reuse previous turn's evidence"
    assert r2.decision.action == Action.ANSWER
    assert r2.answer.source_ids, "rescued answer must still cite its evidence"
    assert set(r2.answer.source_ids).issubset({c.source_id for c in r1.chunks})
    assert len(pipeline._memory[session_id]) == 2


def test_delete_session_clears_temporary_memory(tmp_path):
    """Ending the session (user says 'kết thúc'/'thoát') must purge the
    in-memory context — nothing survives past the session."""
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu tại xã Bình Minh?")
    pipeline.process_text(session_id, "vâng ạ")
    assert len(pipeline._memory.get(session_id, [])) == 2
    pipeline.delete_session(session_id)
    assert session_id not in pipeline._memory


def test_hard_refusal_never_bypassed_by_memory(tmp_path):
    """RED/ORANGE refusals must stay hard even when session memory exists."""
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu tại xã Bình Minh?")
    # Emergency after a normal turn: must never reach the LLM via memory.
    result = pipeline.process_text(session_id, "Tôi bị đau tim, cấp cứu giúp!")
    assert result.decision.zone == Zone.RED
    assert result.answer is None
