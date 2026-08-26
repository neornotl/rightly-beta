"""Small, domain-level safety gates for legally material ambiguity.

These checks deliberately operate on concepts (payment method, measurement
range, benefit group, etc.), rather than benchmark question text.  They are a
cheap deterministic preflight: a clarifying question or an abstention is
preferable to spending an LLM call on a fact pattern whose answer changes with
one missing fact.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional


def _plain(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def _has(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _has_all(text: str, *terms: str) -> bool:
    return all(term in text for term in terms)


@dataclass(frozen=True)
class MaterialityGate:
    """A routing override returned by :func:`assess_materiality`."""

    action: str  # ``clarify`` or ``abstain``
    message: str
    reason: str


def _direct_evidence(query: str, chunks: Iterable[object]) -> bool:
    """Require the requested concepts to co-occur in one retrieved chunk.

    A source merely mentioning a broad topic (for example, poverty standards)
    must not be used to answer a specific benefit/procedure question.
    """
    def chunk_text(chunk: object) -> str:
        # Local retrieval returns RetrievedChunk objects; the dependency-free
        # Vercel handler returns plain dictionaries.  Keep the gate portable
        # across both boundaries instead of treating every public hit as empty.
        if isinstance(chunk, dict):
            return str(chunk.get("text", ""))
        return str(getattr(chunk, "text", ""))

    texts = [_plain(chunk_text(chunk)) for chunk in chunks]
    if not texts:
        return False
    q = _plain(query)
    if _has_all(q, "ho ngheo", "hoc phi"):
        poverty = ("ho ngheo", "ho can ngheo", "chuan ngheo")
        education = ("hoc phi", "mien giam hoc phi", "giam hoc phi")
        needs_certification = _has(q, "xac nhan", "ho so", "thu tuc", "can gi")
        return any(
            _has_all(text, *poverty[:1], *education[:1])
            and (not needs_certification or "xac nhan" in text)
            for text in texts
        )
    if _has_all(q, "quy dao", "ve tinh"):
        return any(
            _has_all(text, "quy dao", "ve tinh")
            and ("chuyen nhuong" not in q or "chuyen nhuong" in text)
            and ("ho so" not in q or "ho so" in text)
            for text in texts
        )
    return True


def _explicit_gender(text: str) -> bool:
    """Detect gender, excluding ``sinh nam 1965`` as a birth-year phrase."""
    text = re.sub(r"\bsinh\s+nam\s+(?:19|20)\d{2}\b", "", text)
    return bool(re.search(r"\b(?:nam|nu)\b", text))


def assess_materiality(query: str, chunks: Iterable[object] = ()) -> Optional[MaterialityGate]:
    """Return a conservative clarify/abstain gate, if one is warranted."""
    q = _plain(query)

    # Delayed pension payments can have several causes.  The corpus cannot
    # diagnose one without the delivery channel/status and an agency check.
    if _has(q, "luong huu", "huu tri") and _has(q, "chua nhan", "cham nhan", "cham chi", "chua duoc nhan", "2 thang", "hai thang", "nhieu thang"):
        return MaterialityGate(
            "clarify",
            "Để kiểm tra việc chậm nhận lương hưu, bác cho biết nhận qua tài khoản hay tiền mặt, có thông báo tạm dừng không, và đã liên hệ cơ quan bảo hiểm xã hội chưa ạ?",
            "pension_payment_context_missing",
        )

    # Age is not itself a BHYT entitlement group; route, card group and the
    # service received can all change the applicable level of coverage.
    if _has(q, "nguoi cao tuoi", "cao tuoi") and _has(q, "bhyt", "bao hiem y te") and _has(q, "quyen loi", "duoc huong", "kham"):
        return MaterialityGate(
            "clarify",
            "Bác cho biết nhóm quyền lợi ghi trên thẻ bảo hiểm y tế, nơi dự định khám, và đang hỏi dịch vụ nào cụ thể để em tra đúng mức hưởng ạ?",
            "health_coverage_facts_missing",
        )

    # Alcohol penalties branch on the measured concentration and vehicle
    # facts.  Never emit a single amount from an underspecified question.
    if _has(q, "ruou", "bia", "nong do con", "con") and _has(q, "lai xe", "xe may", "o to", "phat"):
        has_measurement = bool(re.search(r"\d+(?:[.,]\d+)?\s*(?:mg/l|mg\s*/\s*l|miligam|promil|‰|g/l)", q))
        has_vehicle = _has(q, "xe may", "xe gan may", "o to", "xe dap", "phuong tien")
        if not (has_measurement and has_vehicle):
            return MaterialityGate(
                "clarify",
                "Bạn cho biết kết quả đo nồng độ cồn (nếu có) và loại phương tiện cụ thể để em đối chiếu đúng mức xử phạt ạ?",
                "alcohol_penalty_facts_missing",
            )

    # Personalized retirement dates depend on gender and, where applicable,
    # work conditions.  The phrase ``sinh nam YYYY`` is a birth year, not a
    # supplied gender.
    if _has(q, "nghi huu", "tuoi nghi huu") and _has(q, "sinh", "nam sinh", "nu sinh"):
        has_work_context = _has(q, "dieu kien lao dong", "cong viec nang nhoc", "doc hai", "dac biet", "binh thuong", "lam viec", "dong bhxh", "hop dong")
        if not _explicit_gender(q) or not has_work_context:
            missing = "giới tính và điều kiện công việc" if not _explicit_gender(q) else "điều kiện công việc"
            return MaterialityGate(
                "clarify",
                f"Để xác định mốc nghỉ hưu chính xác, anh/chị cho biết {missing} của mình được không ạ?",
                "retirement_material_facts_missing",
            )

    # High-confidence scope gaps: retrieve only if the requested concepts are
    # present together in one chunk.  Lexically related land/poverty sources
    # therefore cannot be cited as if they answered the request.
    if (_has_all(q, "ho ngheo", "hoc phi") or _has_all(q, "quy dao", "ve tinh")) and not _direct_evidence(q, chunks):
        return MaterialityGate(
            "abstain",
            "Tôi chưa tìm thấy nguồn chính thức trong kho đã kiểm chứng quy định trực tiếp cho trường hợp này, nên không thể kết luận hoặc trích dẫn thay thế. Bạn có thể cung cấp văn bản cụ thể hoặc liên hệ cơ quan chuyên ngành để được hướng dẫn ạ.",
            "direct_evidence_missing",
        )

    return None
