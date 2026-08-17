"""Eval script tests (fixture-driven) + state machine + LLM source-ID guard."""

from __future__ import annotations

import json
from pathlib import Path

from app.dialogue.state_machine import DialogueStateMachine, State, TransitionError
from app.llm.gemini_llm import GeminiLLM
from app.llm.mock_llm import MockLLM
from app.schemas import RetrievedChunk

# ---------- eval scripts ----------


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def test_wer_eval_runs_on_fixture(tmp_path):
    from eval import wer

    fixture = _write_jsonl(
        tmp_path / "wer.jsonl",
        [
            {
                "case_id": 1,
                "accent_group": "northern",
                "reference": "thủ tục cấp giấy xác nhận hộ khẩu",
                "hypothesis": "thủ tục cấp giấy xác nhận hộ khẩu",
            },
            {
                "case_id": 2,
                "accent_group": "northern",
                "reference": "đăng ký khai sinh",
                "hypothesis": "đăng ký khai sinh mới",
            },
        ],
    )
    rows, summary = wer.evaluate_wer(wer.load_jsonl(fixture))
    assert summary["wer"] == round(1 / 12, 4)  # 1 insertion / 12 ref tokens
    assert len(rows) == 2
    assert summary["by_accent_group"]["northern"]["count"] == 2
    assert "SYNTHETIC DEMO - NOT PILOT RESULTS" in summary["note"]
    assert rows[0]["substitutions"] == 0 and rows[0]["insertions"] == 0


def test_retrieval_eval_runs_on_fixture(tmp_path):
    from app.retrieval.bm25_retriever import BM25Retriever
    from app.retrieval.document_loader import DocumentLoader
    from eval import retrieval

    chunks = DocumentLoader(sources_dir="data/sources", chunks_dir=tmp_path).ingest()
    chunks_file = tmp_path / "demo_chunks.jsonl"
    with chunks_file.open("w", encoding="utf-8") as fh:
        for rec in chunks:
            fh.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
    cases = _write_jsonl(
        tmp_path / "retrieval.jsonl",
        [
            {
                "query": "Thủ tục cấp giấy xác nhận hộ khẩu?",
                "expected_source_id": "demo_binhminh_procedures",
            }
        ],
    )
    rows, summary = retrieval.evaluate_retrieval(
        retrieval.load_jsonl(cases), BM25Retriever.from_jsonl(chunks_file)
    )
    assert summary["top1_accuracy"] == 1.0
    assert rows[0]["hit_at_1"] == 1


def test_routing_eval_runs_on_fixture(tmp_path):
    from app.config import Settings
    from app.retrieval.bm25_retriever import BM25Retriever
    from app.retrieval.document_loader import DocumentLoader
    from app.safety.policy import Policy
    from app.safety.router import SafetyRouter
    from eval import routing

    records = DocumentLoader(sources_dir="data/sources", chunks_dir=tmp_path).ingest()
    chunks_file = tmp_path / "demo_chunks.jsonl"
    with chunks_file.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
    cases = _write_jsonl(
        tmp_path / "routing.jsonl",
        [
            {
                "query": "Tôi bị đau tim dữ dội",
                "expected_zone": "RED",
                "expected_action": "ESCALATE",
            },
            {
                "query": "Thủ tục cấp hộ khẩu?",
                "expected_zone": "YELLOW",
                "expected_action": "ANSWER",
            },
        ],
    )
    router = SafetyRouter(settings=Settings(), policy=Policy())
    retriever = BM25Retriever.from_jsonl(chunks_file)
    rows, summary = routing.evaluate_routing(routing.load_jsonl(cases), router, retriever)
    assert summary["zone_accuracy"] == 1.0
    assert summary["action_accuracy"] == 1.0
    assert summary["red_false_safe_rate"] == 0.0
    assert rows[0]["got_zone"] == "RED"


def test_latency_eval_runs_on_fixture(tmp_path):
    from eval import latency

    fixture = _write_jsonl(
        tmp_path / "latency.jsonl",
        [
            {"case_id": 1, "hold_message": True, "asr_ms": 2000, "total_ms": 3000},
            {"case_id": 2, "hold_message": False, "asr_ms": 4000, "total_ms": 5000},
        ],
    )
    rows, summary = latency.evaluate_latency(latency.load_jsonl(fixture))
    assert summary["stages"]["asr_ms"]["p50_ms"] == 3000.0
    assert summary["stages"]["total_ms"]["max_ms"] == 5000.0
    assert summary["hold_message_comparison"]["true"]["asr_ms"]["p50_ms"] == 2000.0


# ---------- R20 answer-quality metrics ----------


def test_answer_quality_numeric_extraction():
    from eval.answer_quality import _numbers

    assert _numbers("5.310.000 đồng") == {"5310000"}
    assert _numbers("từ 500.000 đến 1.000.000") == {"500000", "1000000"}
    assert _numbers("không có số nào") == set()


def test_answer_quality_numeric_accuracy():
    from eval.answer_quality import numeric_accuracy

    answer = "Mức lương tối thiểu vùng I là 5.310.000 đồng."
    chunks_supported = ["Vùng I mức lương tối thiểu tháng 5.310.000 đồng"]
    chunks_missing = ["Vùng I mức lương tối thiểu tháng không ghi số"]
    assert numeric_accuracy(answer, chunks_supported) == 1.0
    assert numeric_accuracy(answer, chunks_missing) == 0.0


def test_answer_quality_faithfulness():
    from eval.answer_quality import retrieval_faithfulness

    assert retrieval_faithfulness(["a", "b"], {"a", "b", "c"}) == 1.0
    assert retrieval_faithfulness(["a", "x"], {"a", "b"}) == 0.5
    assert retrieval_faithfulness([], {"a"}) == 0.0


def test_answer_quality_vacuously_accurate_without_numbers():
    from eval.answer_quality import numeric_accuracy

    assert numeric_accuracy("hồ sơ gồm đơn và căn cước", ["đơn", "căn cước"]) == 1.0


# ---------- LLM source-ID guard ----------


def _chunk(source_id: str) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=f"{source_id}::c000", source_id=source_id, text="x", score=1.0)


def test_llm_cannot_invent_source_ids():
    llm = GeminiLLM(api_key="")
    parsed = llm.enforce_source_ids(
        {"answer_text": "x", "source_ids": ["hacked_source", "demo_binhminh_procedures"]},
        allowed={"demo_binhminh_procedures"},
    )
    assert parsed["source_ids"] == ["demo_binhminh_procedures"]
    assert parsed["_source_ids_sanitized"] is True


def test_mock_llm_deterministic_and_cited():
    chunks = [_chunk("demo_binhminh_procedures")]
    a = MockLLM().generate_answer("hỏi gì đó?", chunks)
    b = MockLLM().generate_answer("hỏi gì đó?", chunks)
    assert a == b
    assert a["source_ids"] == ["demo_binhminh_procedures"]
    assert a["answer_text"]


# ---------- state machine ----------


def test_valid_transition_path():
    machine = DialogueStateMachine()
    machine.transition(State.DISCLAIMER)
    machine.transition(State.LISTENING)
    machine.transition(State.TRANSCRIBING)
    machine.transition(State.RETRIEVING)
    machine.transition(State.SAFETY_CHECK)
    machine.transition(State.HOLDING)
    machine.transition(State.SPEAKING)
    machine.transition(State.LISTENING)
    machine.transition(State.DONE)
    assert machine.is_terminal()


def test_invalid_transition_raises():
    machine = DialogueStateMachine()
    try:
        machine.transition(State.SPEAKING)
        assert False, "expected TransitionError"
    except TransitionError:
        pass


def test_transition_same_state_is_noop():
    machine = DialogueStateMachine()
    assert machine.transition(State.WELCOME) == State.WELCOME


def test_escalation_path_from_listening():
    machine = DialogueStateMachine()
    machine.transition(State.DISCLAIMER)
    machine.transition(State.LISTENING)
    machine.transition(State.ESCALATING)
    machine.transition(State.LISTENING)
    assert machine.state == State.LISTENING


def test_connect_path_from_listening_and_speaking():
    machine = DialogueStateMachine()
    machine.transition(State.DISCLAIMER)
    machine.transition(State.LISTENING)
    machine.transition(State.CONNECTING)
    machine.transition(State.LISTENING)
    machine.transition(State.TRANSCRIBING)
    machine.transition(State.RETRIEVING)
    machine.transition(State.SAFETY_CHECK)
    machine.transition(State.HOLDING)
    machine.transition(State.SPEAKING)
    machine.transition(State.CONNECTING)
    machine.transition(State.DONE)
    assert machine.is_terminal()


def test_connect_invalid_from_welcome():
    machine = DialogueStateMachine()
    try:
        machine.transition(State.CONNECTING)
        assert False, "expected TransitionError"
    except TransitionError:
        pass


def test_connect_parsed_from_voice_commands():
    from app.dialogue.commands import Command, parse_command

    assert parse_command("nối máy giúp tôi") == Command.CONNECT
    assert parse_command("oke") == Command.CONNECT
    assert parse_command("đồng ý kết nối") == Command.CONNECT
    assert parse_command("kết nối tới bộ phận một cửa") == Command.CONNECT
