"""Schema tests: dataclass fields and to_dict round-trips."""

from __future__ import annotations

from app.schemas import (
    Action,
    GroundedAnswer,
    PipelineResult,
    RetrievedChunk,
    SafetyDecision,
    Zone,
)


def test_safety_decision_fields():
    decision = SafetyDecision(
        zone=Zone.YELLOW,
        action=Action.CLARIFY,
        reason_codes=["AMBIGUOUS_QUERY"],
        user_message="xin nói rõ hơn",
        requires_human=False,
    )
    d = decision.to_dict()
    assert d["zone"] == "YELLOW"
    assert d["action"] == "CLARIFY"
    assert d["reason_codes"] == ["AMBIGUOUS_QUERY"]
    assert d["user_message"] == "xin nói rõ hơn"
    assert d["requires_human"] is False


def test_grounded_answer_fields():
    answer = GroundedAnswer(
        answer_text="Nội dung trả lời",
        spoken_citation="Nguồn demo",
        source_ids=["demo_binhminh_procedures"],
        limitations=["DEMO"],
        next_step="Hỏi tiếp",
    )
    d = answer.to_dict()
    assert d["answer_text"] == "Nội dung trả lời"
    assert d["source_ids"] == ["demo_binhminh_procedures"]


def test_pipeline_result_roundtrip():
    result = PipelineResult(
        session_id="abc123",
        query="Thủ tục cấp hộ khẩu?",
        decision=SafetyDecision(zone=Zone.YELLOW, action=Action.ANSWER),
        answer=GroundedAnswer(
            answer_text="x",
            source_ids=["s1"],
            limitations=[],
            next_step="",
        ),
        chunks=[RetrievedChunk(chunk_id="s1::c000", source_id="s1", text="x", score=2.0)],
        latencies_ms={"retrieval_ms": 1.0},
    )
    d = result.to_dict()
    assert d["decision"]["zone"] == "YELLOW"
    assert d["chunks"][0]["chunk_id"] == "s1::c000"
    assert d["answer"]["source_ids"] == ["s1"]


def test_enums_are_stable():
    assert [z.value for z in Zone] == ["YELLOW", "ORANGE", "RED"]
    assert [a.value for a in Action] == ["ANSWER", "CLARIFY", "GUIDE", "REFUSE", "ESCALATE"]
