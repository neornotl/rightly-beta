"""Generic output checks for evidence-grounded legal answers.

This module deliberately contains no FAQ answers or case-specific legal rules.
It checks only the relationship between a model response and the excerpts the
pipeline supplied to it.  The checks are intentionally conservative: an issue
causes the normal insufficient-evidence path rather than allowing an
unsupported amount, deadline, or citation to be spoken as fact.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from app.schemas import GroundedAnswer, RetrievedChunk


_NUMBER = r"\d[\d.,]*"
_AMOUNT = re.compile(rf"({_NUMBER})\s*(triệu|nghìn|đồng|vnd)\b", re.IGNORECASE)
_PERCENT = re.compile(rf"({_NUMBER})\s*%")
_DURATION = re.compile(
    rf"({_NUMBER})\s*(ngày|tháng|năm)\b", re.IGNORECASE
)
_ARTICLE = re.compile(r"\bđiều\s+(\d+[a-z]?)\b", re.IGNORECASE)

_UNDERCUTTING = re.compile(
    r"(?:chưa|không)\s+(?:có|nêu|thấy|được cung cấp|quy định)"
    r"[^.\n]{0,100}(?:cụ thể|trực tiếp|đủ|thông tin)",
    re.IGNORECASE,
)

_CONDITIONAL_SCOPE = re.compile(
    r"\b(?:nếu|khi|trường hợp|đối với|tùy thuộc|trừ trường hợp|trong trường hợp)\b",
    re.IGNORECASE,
)
_GENERALIZING = re.compile(
    r"\b(?:mọi|tất cả|luôn luôn|luôn|đều phải|bất kể|trong mọi trường hợp)\b",
    re.IGNORECASE,
)
_GENERALIZED_DEADLINE = re.compile(
    r"(?:\b(?:mọi|tất cả|luôn luôn|luôn|đều phải|bất kể|trong mọi trường hợp)\b[^.\n]{0,90}\b\d[\d.,]*\s*(?:ngày|tháng|năm)\b|\b\d[\d.,]*\s*(?:ngày|tháng|năm)\b[^.\n]{0,90}\b(?:mọi|tất cả|luôn luôn|luôn|đều phải|bất kể|trong mọi trường hợp)\b)",
    re.IGNORECASE,
)
_DURATION_CLAIM = re.compile(r"\b\d[\d.,]*\s*(?:ngày|tháng|năm)\b", re.IGNORECASE)
_SCOPE_QUALIFIER = re.compile(
    r"\b(?:nếu|khi|trường hợp|đối với|tùy thuộc|trừ trường hợp|trong trường hợp|"
    r"kể từ|sau khi|nhận đủ|hồ sơ hợp lệ|có thể lâu hơn|có thể kéo dài)\b",
    re.IGNORECASE,
)
_PENALTY = re.compile(
    r"\b(?:mức phạt|phạt tiền|xử phạt|tước quyền|tước giấy phép|giữ xe|trừ điểm)\b",
    re.IGNORECASE,
)


def _plain(value: str) -> str:
    value = str(value or "").replace("đ", "d").replace("Đ", "D")
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.casefold().split())


def _number_key(value: str) -> str:
    """Compare OCR/legal number formats without changing their meaning."""
    digits = re.sub(r"[^0-9]", "", value or "")
    return digits.lstrip("0") or "0"


def _has_number_with_unit(text: str, number: str, unit: str) -> bool:
    key = _number_key(number)
    boundary = r"\b" if unit != "%" else ""
    for match in re.finditer(rf"({_NUMBER})\s*({re.escape(unit)}){boundary}", text, re.IGNORECASE):
        if _number_key(match.group(1)) == key:
            return True
    return False


def _claim_supported(answer_text: str, evidence_text: str, query: str) -> list[str]:
    """Return unsupported critical claim issue codes.

    Only claims that are likely to change legal advice are checked.  Ordinary
    prose and computed results are left to the structured reasoning contract.
    """
    issues: list[str] = []
    q = _plain(query)
    for match in _AMOUNT.finditer(answer_text):
        if not _has_number_with_unit(evidence_text, match.group(1), match.group(2)):
            issues.append("unsupported_amount")
    for match in _PERCENT.finditer(answer_text):
        if not _has_number_with_unit(evidence_text, match.group(1), "%"):
            issues.append("unsupported_percentage")
    if any(marker in q for marker in ("bao lau", "thoi han", "khi nao", "thoi gian")):
        for match in _DURATION.finditer(answer_text):
            if not _has_number_with_unit(evidence_text, match.group(1), match.group(2)):
                issues.append("unsupported_deadline")
    for match in _ARTICLE.finditer(answer_text):
        if not re.search(rf"\bđiều\s+{re.escape(match.group(1))}\b", evidence_text, re.IGNORECASE):
            issues.append("unsupported_article")
    return list(dict.fromkeys(issues))


def validate_evidence_contract(
    query: str,
    answer: GroundedAnswer,
    chunks: Iterable[RetrievedChunk],
    *,
    evidence_used: Iterable[str] = (),
) -> list[str]:
    """Check that an answer's critical claims and selected citations are grounded.

    ``evidence_used`` is optional for compatibility with legacy backends.  If
    present, citations are restricted to the model's selected source set and
    the checks inspect only those excerpts.  This prevents a model from citing
    every retrieved document merely because one of them happened to contain a
    related word.
    """
    all_chunks = list(chunks)
    selected = {str(s).strip() for s in evidence_used if str(s).strip()}
    available = {c.source_id for c in all_chunks}
    issues: list[str] = []
    if selected and not selected.issubset(available):
        issues.append("evidence_source_not_retrieved")
    cited = {str(s).strip() for s in answer.source_ids if str(s).strip()}
    if selected and cited - selected:
        issues.append("citation_not_in_selected_evidence")
    usable = selected or cited or available
    evidence_text = "\n".join(
        c.text for c in all_chunks if c.source_id in usable
    )
    if not evidence_text:
        return issues + ["no_evidence_text"]

    issues.extend(_claim_supported(answer.answer_text or "", evidence_text, query))

    # A model must not claim that a requested answer is absent when the supplied
    # excerpts visibly contain the requested class of rule.  This is a generic
    # contradiction check, not a list of legal answers.
    q = _plain(query)
    a = _plain(answer.answer_text)
    wants = []
    if any(x in q for x in ("giay to", "ho so", "can gi", "thu tuc", "lam sao")):
        wants.extend(("giay to", "ho so", "nop", "thu tuc", "co quan"))
    if any(x in q for x in ("bao lau", "thoi han", "khi nao", "thoi gian")):
        wants.extend(("ngay", "thang", "nam", "thoi han", "giai quyet"))
    if any(x in q for x in ("phat", "muc phat", "bao nhieu")):
        wants.extend(("phat", "muc", "dong"))
    normalized_evidence = _plain(evidence_text)
    if wants and _UNDERCUTTING.search(answer.answer_text or ""):
        if any(marker in normalized_evidence for marker in wants):
            issues.append("answer_undercuts_direct_evidence")

    # A deadline in a conditional branch must not be presented as universal.
    # This is deliberately structural: it does not encode any particular law
    # or benchmark case.
    if (
        any(marker in q for marker in ("bao lau", "thoi han", "khi nao", "thoi gian"))
        and _CONDITIONAL_SCOPE.search(evidence_text)
        and _GENERALIZED_DEADLINE.search(answer.answer_text or "")
    ):
        issues.append("deadline_scope_generalized")

    # Also catch the subtler form where the first sentence states a duration
    # without any qualifier, while the evidence makes that duration branch-
    # dependent.  A correct number alone is not enough when its legal scope
    # was omitted from the headline answer.
    if (
        any(marker in q for marker in ("bao lau", "thoi han", "khi nao", "thoi gian"))
        and _CONDITIONAL_SCOPE.search(evidence_text)
    ):
        first_sentence = re.split(r"(?<=[.!?])\s+|\n+", answer.answer_text or "", maxsplit=1)[0]
        if _DURATION_CLAIM.search(first_sentence) and not _SCOPE_QUALIFIER.search(first_sentence):
            issues.append("deadline_scope_omitted")

    # Keep answers focused.  Mentioning a consequence is fine when the user
    # asks about sanctions or when it is the direct answer; otherwise a full
    # penalty section is usually unrelated noise and can mislead the reader.
    asks_penalty = any(marker in q for marker in ("phat", "xu phat", "che tai", "tien phat"))
    if not asks_penalty and _PENALTY.search(answer.answer_text or ""):
        if re.search(r"(?:mức phạt|phạt tiền|xử phạt|tước quyền)[^\n]{0,100}\d", answer.answer_text or "", re.IGNORECASE):
            issues.append("unrequested_penalty_detail")
    return list(dict.fromkeys(issues))
