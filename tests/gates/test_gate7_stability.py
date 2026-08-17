"""GATE 7 — Stability & error recovery (Luna gate #7).

- 30 continuous sessions x 2 queries: no crash, error rate < 5%.
- Fault injection: an LLM failure must degrade to a graceful refusal (no
  crash, llm_failure recorded); a TTS failure must not break the reply
  (tts_failure recorded, result still returned); a retriever failure must
  degrade to a graceful refusal (retriever_failure recorded, no crash).
"""

from __future__ import annotations

from app.schemas import Action, Zone

SESSION_QUERIES = [
    "Thủ tục đăng ký khai sinh cho cháu cần những gì?",
    "Tuổi nghỉ hưu năm 2026 là bao nhiêu?",
    "Tôi bị đau tim, cấp cứu!",
    "Tách hộ khẩu cho con đi làm xa cần giấy tờ gì?",
]


def test_gate7_thirty_sessions_no_crash(offline_pipeline):
    sessions = 30
    errors = 0
    for _ in range(sessions):
        session_id = offline_pipeline.create_session()
        try:
            for q in SESSION_QUERIES:
                result = offline_pipeline.process_text(session_id, q)
                assert result is not None
                assert result.decision.zone in (Zone.YELLOW, Zone.ORANGE, Zone.RED)
        except Exception:  # noqa: BLE001 - gate must count, not fail fast
            errors += 1
        finally:
            offline_pipeline.delete_session(session_id)
    error_rate = errors / sessions
    assert error_rate < 0.05, f"error rate {error_rate:.0%} >= 5% over {sessions} sessions"
    assert errors == 0, f"{errors}/{sessions} sessions crashed"


def test_gate7_llm_failure_degrades_to_refusal(offline_pipeline):
    class BoomLLM:
        name = "boom"

        def generate_answer(self, query, chunks, max_chars=2000, history=None):
            raise TimeoutError("upstream timed out")

    offline_pipeline.llm = BoomLLM()  # type: ignore[assignment]
    session_id = offline_pipeline.create_session()
    result = offline_pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu?")
    records = json_dumps(offline_pipeline)  # read BEFORE session deletion
    offline_pipeline.delete_session(session_id)
    assert result.answer is None
    assert result.decision.action in (Action.REFUSE, Action.CLARIFY)
    assert "llm_failure" in records


def test_gate7_tts_failure_does_not_break_reply(offline_pipeline):
    class BoomTTS:
        name = "boom-tts"

        def speak_result(self, result) -> str:
            return "Thông tin tham khảo theo nguồn đã trích dẫn."

        def synthesize(self, text, out_path):
            raise RuntimeError("tts engine down")

    offline_pipeline.tts = BoomTTS()  # type: ignore[assignment]
    session_id = offline_pipeline.create_session()
    result = offline_pipeline.process_text(session_id, "Tuổi nghỉ hưu năm 2026 là bao nhiêu?")
    records = json_dumps(offline_pipeline)  # read BEFORE session deletion
    offline_pipeline.delete_session(session_id)
    assert result.answer is not None, "TTS failure must not suppress the legal answer"
    assert "tts_failure" in records


def test_gate7_empty_retrieval_refused_gracefully(offline_pipeline):
    class EmptyRetriever:
        name = "empty"

        def search(self, query, top_k=5):
            return []

    offline_pipeline.retriever = EmptyRetriever()  # type: ignore[assignment]
    session_id = offline_pipeline.create_session()
    result = offline_pipeline.process_text(session_id, "Tổng thống Mỹ tên là gì?")
    offline_pipeline.delete_session(session_id)
    assert result.answer is None
    assert result.decision.action == Action.REFUSE


def test_gate7_retriever_fault_degrades_to_refusal(offline_pipeline):
    class BoomRetriever:
        name = "boom-retriever"

        def search(self, query, top_k=5):
            raise RuntimeError("index corrupt")

    offline_pipeline.retriever = BoomRetriever()  # type: ignore[assignment]
    session_id = offline_pipeline.create_session()
    result = offline_pipeline.process_text(session_id, "Thủ tục cấp hộ khẩu?")
    records = json_dumps(offline_pipeline)  # read BEFORE session deletion
    offline_pipeline.delete_session(session_id)
    assert result is not None, "retriever fault must not crash the session"
    assert result.answer is None
    assert result.decision.action in (Action.REFUSE, Action.CLARIFY)
    assert "retriever_failure" in records


def json_dumps(pipeline) -> str:
    import json

    return json.dumps(pipeline.store.logger.read_records(), ensure_ascii=False)
