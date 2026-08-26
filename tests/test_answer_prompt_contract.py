"""Regression checks for generic answer-quality instructions."""

from app.llm.prompts import AGENTIC_REASONING_SYSTEM, SYSTEM_PROMPT


def test_prompt_preserves_scope_and_conditional_documents():
    text = SYSTEM_PROMPT + AGENTIC_REASONING_SYSTEM
    assert "phạm vi áp dụng" in text
    assert "Không biến một nhánh" in text
    assert "giấy tờ bắt buộc" in text
    assert "tùy hồ sơ" in text


def test_prompt_requires_current_authority_and_focus():
    text = SYSTEM_PROMPT + AGENTIC_REASONING_SYSTEM
    assert "không suy ra \"hiện hành\"" in text
    assert "Chỉ trả lời đúng ý người dân hỏi" in text
    assert "Không thêm nội dung ngoài câu hỏi" in text
