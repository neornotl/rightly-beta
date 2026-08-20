"""Hybrid assistant tests: general chat, consent, RAM-only profile and RAG hops."""

from __future__ import annotations

from tests.test_pipeline_mock import _pipeline


def test_general_personal_fact_is_silently_kept_in_ram(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()

    result = pipeline.process_text(session_id, "Tôi là nam, sinh năm 1964.")

    assert result.answer is not None
    assert "đồng ý" not in result.answer.answer_text.lower()
    context = pipeline._hybrid_sessions[session_id]
    assert context.profile
    assert context.pending_profile_facts == []


def test_profile_is_deleted_with_current_session(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    pipeline.process_text(session_id, "Tôi là nam, sinh năm 1964.")

    context = pipeline._hybrid_sessions[session_id]
    assert context.profile

    pipeline.delete_session(session_id)
    assert session_id not in pipeline._hybrid_sessions
    assert session_id not in pipeline._memory


def test_consent_words_are_normal_chat_without_pending_prompt(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    pipeline.process_text(session_id, "Không")

    context = pipeline._hybrid_sessions[session_id]
    assert context.profile == {}
    assert context.pending_profile_facts == []


def test_legal_query_uses_and_keeps_current_turn_facts_in_ram(tmp_path):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()

    result = pipeline.process_text(
        session_id,
        "Tôi là nam sinh năm 1964, đóng BHXH 30 năm, khi nào được nghỉ hưu?",
    )

    assert result.answer is not None
    assert pipeline._hybrid_sessions[session_id].profile


def test_general_chat_recovers_from_one_llm_failure(tmp_path, monkeypatch):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    original = pipeline.llm.generate_answer
    general_calls = 0

    def fail_first_general(query, chunks, **kwargs):
        nonlocal general_calls
        if kwargs.get("system_prompt") and "trợ lý AI đa năng" in kwargs["system_prompt"]:
            general_calls += 1
            if general_calls == 1:
                raise RuntimeError("temporary general failure")
        return original(query, chunks, **kwargs)

    monkeypatch.setattr(pipeline.llm, "generate_answer", fail_first_general)
    result = pipeline.process_text(session_id, "Bạn có thể giải thích ngắn gọn về trí tuệ nhân tạo không?")

    assert general_calls == 2
    assert result.answer is not None
    assert "đã nhận được tin nhắn" not in result.answer.answer_text.lower()


def test_multi_hop_is_bounded_and_deduplicates_chunks(tmp_path, monkeypatch):
    pipeline = _pipeline(tmp_path)
    session_id = pipeline.create_session()
    initial = pipeline._retrieve("hộ khẩu", session_id, pipeline.top_k)
    calls = []

    def not_enough(*args, **kwargs):
        calls.append(1)
        return {"sufficient": False, "next_queries": ["hộ khẩu", "thủ tục hộ khẩu"]}

    monkeypatch.setattr(pipeline.llm, "generate_answer", not_enough)
    chunks = pipeline._multi_hop_retrieve("hộ khẩu", session_id, initial)

    assert len(calls) == 2
    assert len({(chunk.source_id, chunk.chunk_id) for chunk in chunks}) == len(chunks)
