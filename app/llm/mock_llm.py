"""Mock LLM: deterministic, template-based answer generation from chunks.

No model, no API. Used as the default backend and as the safe fallback when a
real backend fails. Never invents source IDs (only uses provided chunk
source_ids).

Round 19 council consensus: answers follow hotline agent structure:
1. Chào & xác nhận → 2. Kết luận ngắn → 3. Hướng dẫn hành động →
4. Trích dẫn mềm → 5. Mời hỏi tiếp
"""

from __future__ import annotations

import json
import re
from typing import Optional

from app.llm.base import BaseLLM
from app.llm.prompts import TEMPLATES, clean_spoken_title, shorten_spoken_citation
from app.schemas import RetrievedChunk

#: Intent keyword -> spoken topic (council R23/R24: no raw query echo).
_TOPIC_MAP = [
    ("tuổi nghỉ hưu", "tuổi nghỉ hưu theo lộ trình tăng dần"),
    ("lương hưu", "chế độ lương hưu"),
    ("bảo hiểm xã hội", "bảo hiểm xã hội"),
    ("bảo hiểm y tế", "bảo hiểm y tế"),
    ("kết hôn", "quy định về kết hôn"),
    ("ly hôn", "quy định về ly hôn"),
    ("khai sinh", "thủ tục đăng ký khai sinh"),
    ("căn cước công dân", "thủ tục cấp căn cước công dân"),
    ("đất đai", "quy định về đất đai"),
    ("thừa kế", "quy định về thừa kế"),
]


class MockLLM(BaseLLM):
    name = "mock"

    def generate_answer(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        max_chars: int = 2000,
        history: Optional[list[dict]] = None,
    ) -> dict:
        if not chunks:
            raise ValueError("MockLLM requires at least one retrieved chunk.")

        top = self._pick_content_chunk(chunks, query)
        source_ids = list(dict.fromkeys(c.source_id for c in chunks))

        # Extract topic/keywords from query for template
        topic = self._extract_topic(query)
        core = self._summarize(top.text)

        # Build citation (spoken title only; raw source codes stripped)
        raw_title = top.metadata.title if top.metadata else top.source_id
        citation = shorten_spoken_citation(f"theo {clean_spoken_title(raw_title)}")

        # Determine situation
        situation = self._classify_situation(query, chunks)

        # Fill template
        if situation == "answer_full":
            answer_text = TEMPLATES["answer_full"].format(
                topic=topic, core=core, citation=citation
            )
        elif situation == "insufficient":
            answer_text = TEMPLATES["insufficient"].format(citation=citation)
        elif situation == "off_scope":
            answer_text = TEMPLATES["off_scope"].format(agency="cơ quan có thẩm quyền", citation=citation)
        elif situation == "expired":
            answer_text = TEMPLATES["expired"].format(doc="văn bản cũ", replacement="văn bản mới", citation=citation)
        elif situation == "clarify":
            answer_text = TEMPLATES["clarify"].format(needed="thông tin chi tiết", citation=citation)
        else:
            answer_text = TEMPLATES["answer_full"].format(
                topic=topic, core=core, citation=citation
            )

        spoken = f"Thông tin theo {citation}."
        limitations = ["Đây là dữ liệu DEMO, không phải hướng dẫn chính thức."]
        next_step = "Anh/chị cần em giải thích thêm phần nào không ạ?"

        return {
            "answer_text": answer_text[:max_chars],
            "spoken_citation": spoken,
            "source_ids": source_ids,
            "limitations": limitations,
            "next_step": next_step,
        }

    def _classify_situation(self, query: str, chunks: list[RetrievedChunk]) -> str:
        """Simple heuristic to pick template."""
        query_lower = query.lower()
        if any(kw in query_lower for kw in ["hết hiệu lực", "cũ", "trước đây"]):
            return "expired"
        if any(kw in query_lower for kw in ["gì", "sao", "thế nào", "?"]) and len(chunks) < 2:
            return "clarify"
        if any(kw in query_lower for kw in ["khẩn cấp", "113", "115", "gây án", "bị bắt"]):
            return "criminal"
        if any(kw in query_lower for kw in ["ngoài phạm vi", "không liên quan", "tự do ngôn luận", "tôn giáo"]):
            return "off_scope"
        return "answer_full"

    def _extract_topic(self, query: str) -> str:
        """Extract a short spoken topic from the query.

        Council R23/R24: NEVER echo the raw query or truncate it with '...'.
        Uses the intent keyword map first, then strips question words from a
        copy; falls back to a generic topic.
        """
        q = query.lower()
        for keyword, topic in _TOPIC_MAP:
            if keyword in q:
                return topic
        topic = re.sub(
            r"^(theo quy định của|theo quy định|theo)\s+",
            "",
            query,
            flags=re.IGNORECASE,
        )
        topic = re.sub(
            r"^(làm sao|thế nào|như thế nào|bao nhiêu|khi nào|ở đâu|ai|gì|cái gì)\s+",
            "",
            topic,
            flags=re.IGNORECASE,
        )
        topic = topic.strip("? ").strip()
        words = topic.split()
        if len(words) > 8:
            topic = " ".join(words[:8])
        return topic or "vấn đề này"

    def _pick_content_chunk(self, chunks: list[RetrievedChunk], query: str = "") -> RetrievedChunk:
        """Prefer chunk most relevant to query (contains query keywords)."""
        query_kws = set(re.findall(r"\w+", query.lower()))
        best = None
        best_score = -1
        for chunk in chunks:
            first_line = chunk.text.strip().splitlines()[0] if chunk.text.strip() else ""
            if first_line.startswith("#"):
                continue
            if "LƯU Ý QUAN TRỌNG" in chunk.text[:200].upper():
                continue
            # Score by keyword overlap
            text_lower = chunk.text.lower()
            score = sum(1 for kw in query_kws if kw in text_lower)
            if score > best_score:
                best_score = score
                best = chunk
        return best or chunks[0]

    @staticmethod
    def _summarize(text: str, max_sentences: int = 2) -> str:
        import re
        # Priority: extract sentences with numbers (ages, years, months, percentages)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        clean = [s for s in sentences if not s.startswith(("#", "*", "-", ">", "="))]
        if not clean:
            clean = sentences
        # Boost sentences with numbers
        def num_score(s):
            return len(re.findall(r"\d+", s))
        clean.sort(key=num_score, reverse=True)
        return " ".join(clean[:max_sentences])

    @staticmethod
    def to_json(doc: dict) -> str:
        return json.dumps(doc, ensure_ascii=False)