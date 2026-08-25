"""Small, bounded query expansion for Vietnamese legal retrieval.

The LLM remains the semantic query planner.  These aliases only protect the
retrieval layer from common speech/keyboard forms (especially Vietnamese text
without tone marks), and never invent a source or an answer.
"""

from __future__ import annotations

import re
import unicodedata


_MARKS = re.compile(r"[\u0300-\u036f]")


def strip_diacritics(text: str) -> str:
    """Return a stable, whitespace-collapsed Vietnamese matching form."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = _MARKS.sub("", text)
    return " ".join(text.casefold().split())


def expand_legal_query(query: str, *, limit: int = 8) -> list[str]:
    """Return the original query plus a few safe, topic-specific variants.

    BM25 already matches accents insensitively.  The extra variants are useful
    because a short/no-diacritic query can otherwise rank unrelated documents
    containing a frequent token such as ``quy dinh`` or ``vuot`` above the
    actual traffic rule.  Keep this list deliberately small and deterministic.
    """
    original = " ".join(str(query or "").split())
    if not original:
        return []

    plain = strip_diacritics(original)
    variants: list[str] = [original]

    # "vượt đèn đỏ", "đèn đỏ", and the statutory phrase all refer to the
    # same traffic-light offence in the current traffic corpus.
    red_light = bool(
        re.search(r"\bvuot\s+den\s+do\b", plain)
        or re.search(r"\bden\s+do\b", plain)
        or re.search(r"\bden\s+tin\s+hieu\b", plain)
    )
    if red_light:
        variants.extend(
            [
                "vượt đèn đỏ không chấp hành hiệu lệnh đèn tín hiệu giao thông",
                "phạt tiền vượt đèn đỏ Nghị định 168/2024",
                "người điều khiển xe không chấp hành hiệu lệnh của đèn tín hiệu giao thông",
            ]
        )

    # A common paraphrase used in speech/ASR for the same offence.
    if "khong chap hanh" in plain and "den" in plain and "giao thong" in plain:
        variants.append("không chấp hành hiệu lệnh của đèn tín hiệu giao thông Nghị định 168/2024")

    # Frequent short legal topics from keyboard/ASR input.  These are
    # canonical corpus phrases, not answers, and only add one focused query.
    if re.search(r"\bcan\s+cuoc(?:\s+cong\s+dan)?\b", plain):
        variants.append("thủ tục cấp căn cước công dân hồ sơ giấy tờ")
    elif re.search(r"\bho\s+chieu\b", plain):
        variants.append("thủ tục cấp hộ chiếu hồ sơ giấy tờ")
    elif re.search(r"\bso\s+do\b", plain):
        variants.append("sổ đỏ giấy chứng nhận quyền sử dụng đất thủ tục")

    result: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        value = " ".join(str(variant).split())
        key = strip_diacritics(value)
        if value and key not in seen:
            result.append(value)
            seen.add(key)
        if len(result) >= max(1, limit):
            break
    return result
