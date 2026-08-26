"""Contract tests for evidence-grounded answer quality.

These tests exercise generic relationships between an answer and retrieved
excerpts; they intentionally do not encode a legal answer for any benchmark
case.
"""

from app.evidence_contract import validate_evidence_contract
from app.schemas import GroundedAnswer, RetrievedChunk


def _chunk(text: str, source: str = "law") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"{source}::c001",
        source_id=source,
        text=text,
        score=1.0,
    )


def test_critical_amount_must_appear_with_same_unit():
    chunks = [_chunk("Điều 7. Phạt tiền từ 4.000.000 đồng đến 6.000.000 đồng.")]
    ok = GroundedAnswer("Mức phạt từ 4.000.000 đồng đến 6.000.000 đồng.", source_ids=["law"])
    bad = GroundedAnswer("Mức phạt là 8.000.000 đồng.", source_ids=["law"])
    assert validate_evidence_contract("mức phạt bao nhiêu", ok, chunks) == []
    assert "unsupported_amount" in validate_evidence_contract("mức phạt bao nhiêu", bad, chunks)


def test_selected_evidence_restricts_citations():
    chunks = [_chunk("Điều 1. Hồ sơ gồm tờ khai.", "direct"), _chunk("Điều 2. Nội dung khác.", "other")]
    answer = GroundedAnswer("Hồ sơ gồm tờ khai.", source_ids=["direct", "other"])
    issues = validate_evidence_contract(
        "cần giấy tờ gì", answer, chunks, evidence_used=["direct"]
    )
    assert "citation_not_in_selected_evidence" in issues


def test_answer_cannot_deny_rule_present_in_evidence():
    chunks = [_chunk("Điều 9. Người yêu cầu nộp tờ khai và giấy chứng sinh.")]
    answer = GroundedAnswer(
        "Các văn bản hiện chưa nêu hồ sơ cụ thể.", source_ids=["law"]
    )
    issues = validate_evidence_contract("đăng ký khai sinh cần giấy tờ gì", answer, chunks)
    assert "answer_undercuts_direct_evidence" in issues


def test_unsupported_article_is_rejected_without_case_specific_logic():
    chunks = [_chunk("Điều 9. Người yêu cầu nộp tờ khai.")]
    answer = GroundedAnswer("Căn cứ Điều 10, người dân nộp tờ khai.", source_ids=["law"])
    issues = validate_evidence_contract("thủ tục cần gì", answer, chunks)
    assert "unsupported_article" in issues


def test_deadline_and_percentage_claims_use_evidence_units():
    chunks = [_chunk("Giải quyết trong 01 ngày; mức hưởng là 80%.")]
    answer = GroundedAnswer(
        "Giải quyết trong 1 ngày, mức hưởng 80%.", source_ids=["law"]
    )
    assert validate_evidence_contract("thời hạn bao lâu", answer, chunks) == []
    unsupported = GroundedAnswer(
        "Giải quyết trong 5 ngày, mức hưởng 90%.", source_ids=["law"]
    )
    issues = validate_evidence_contract("thời hạn bao lâu", unsupported, chunks)
    assert "unsupported_deadline" in issues
    assert "unsupported_percentage" in issues


def test_conditional_deadline_cannot_be_generalized():
    chunks = [_chunk("Hồ sơ đầy đủ được giải quyết trong 03 ngày; nếu cần xác minh thì kéo dài theo quy định.")]
    answer = GroundedAnswer(
        "Mọi hồ sơ luôn được giải quyết trong 03 ngày.", source_ids=["law"]
    )
    issues = validate_evidence_contract("thời hạn giải quyết bao lâu", answer, chunks)
    assert "deadline_scope_generalized" in issues


def test_unrequested_numeric_penalty_is_flagged_as_noise():
    chunks = [_chunk("Thủ tục gồm tờ khai và giấy tờ tùy thân.")]
    answer = GroundedAnswer(
        "Hồ sơ gồm tờ khai. Mức phạt là 2.000.000 đồng.", source_ids=["law"]
    )
    issues = validate_evidence_contract("thủ tục cần giấy tờ gì", answer, chunks)
    assert "unrequested_penalty_detail" in issues


def test_penalty_question_may_include_numeric_penalty():
    chunks = [_chunk("Hành vi bị phạt tiền 2.000.000 đồng.")]
    answer = GroundedAnswer(
        "Hành vi bị phạt tiền 2.000.000 đồng.", source_ids=["law"]
    )
    issues = validate_evidence_contract("mức phạt bao nhiêu", answer, chunks)
    assert "unrequested_penalty_detail" not in issues


def test_unqualified_deadline_headline_is_rejected():
    chunks = [_chunk(
        "Thời hạn chung là 03 ngày làm việc kể từ khi nhận đủ hồ sơ hợp lệ; "
        "nếu cần xác minh thì thực hiện sau khi có văn bản trả lời."
    )]
    answer = GroundedAnswer(
        "Dạ, thủ tục được giải quyết trong 03 ngày làm việc.\n"
        "Căn cứ và giải thích: ...",
        source_ids=["law"],
    )
    issues = validate_evidence_contract(
        "Xác nhận tình trạng hôn nhân mất bao lâu?", answer, chunks
    )
    assert "deadline_scope_omitted" in issues
