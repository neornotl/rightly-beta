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
        # Keep the mock backend compatible with the two-step Agentic RAG
        # contract. This makes tests exercise parsing/grounding metadata
        # instead of silently falling back when analysis has no chunks.
        if not chunks and "Hãy phân tích và sinh ra JSON" in query:
            question = query.split('Câu hỏi của người dân:', 1)[-1]
            return {
                "answer_text": json.dumps(self._agentic_analysis(question), ensure_ascii=False),
                "spoken_citation": "",
                "source_ids": [],
                "limitations": [],
                "next_step": "",
            }
        if not chunks:
            raise ValueError("MockLLM requires at least one retrieved chunk.")

        if "excluded_chunks" in query and "EVIDENCE" in query:
            top = self._pick_content_chunk(chunks, query)
            question = query.split("CÂU HỎI:", 1)[1].split("\n", 1)[0] if "CÂU HỎI:" in query else query
            facts = self._extract_facts(question)
            missing = []
            if "nghỉ hưu" in question.lower() and not self._has_gender(question):
                missing.append("giới tính")
            birth_year = next((f["value"] for f in facts if f["field"] == "birth_year"), None)
            gender = next((f["value"] for f in facts if f["field"] == "gender"), None)
            if birth_year and gender == "nam":
                retirement_year = int(birth_year) + 62
                source_id = top.source_id
                legal_reference = {
                    "nd135_2020": "Nghị định số 135/2020/NĐ-CP về quy định tuổi nghỉ hưu"
                }.get(source_id, top.metadata.title if top.metadata else source_id)
                return {
                    "answer_text": (
                        f"Dạ, theo quy định hiện hành, anh là nam sinh năm {birth_year}; trong điều kiện "
                        f"lao động bình thường, anh dự kiến đủ tuổi nghỉ hưu vào năm "
                        f"{retirement_year}.\n\n"
                        "Căn cứ và giải thích:\n"
                        f"- {legal_reference}, Điều 4: tuổi nghỉ hưu bình thường của nam là 62 tuổi.\n"
                        f"- Phép tính theo năm sinh: {birth_year} + 62 = {retirement_year}.\n"
                        "- Vì chỉ có năm sinh, chưa thể xác định chính xác tháng và ngày "
                        "nghỉ hưu; kết quả cũng có thể khác nếu thuộc nhóm công việc đặc thù.\n\n"
                        f"Kết luận: Dự kiến anh đủ tuổi nghỉ hưu vào năm {retirement_year}; "
                        "cần ngày, tháng sinh và điều kiện lao động để chốt thời điểm chính xác."
                    ),
                    "spoken_citation": f"Theo {legal_reference}.",
                    "source_ids": [source_id],
                    "limitations": ["Cần ngày, tháng sinh và điều kiện lao động để xác định thời điểm chính xác."],
                    "next_step": "Nếu muốn tính chính xác, hãy cung cấp ngày tháng sinh và cho biết công việc có thuộc nhóm đặc thù không.",
                    "reasoning": {
                        "extracted_facts": facts,
                        "missing_facts": [],
                        "applicable_rules": [{"rule": "Nam đủ 62 tuổi trong điều kiện bình thường", "evidence": source_id}],
                        "calculations": [{"expression": f"{birth_year} + 62", "result": str(retirement_year)}],
                        "conflicts": [],
                        "confidence": "medium",
                        "evidence_used": [source_id],
                        "key_claims": [{"claim": f"Nam nghỉ hưu ở tuổi 62; sinh năm {birth_year} dự kiến đủ tuổi năm {retirement_year}.", "evidence": source_id}],
                        "excluded_chunks": [],
                    },
                }
            return {
                **self.generate_answer(
                    query=query.split("\n\nEVIDENCE", 1)[0],
                    chunks=chunks,
                    max_chars=max_chars,
                    history=history,
                ),
                "reasoning": {
                    "extracted_facts": facts,
                    "missing_facts": missing,
                    "applicable_rules": [{"rule": "Đối chiếu điều kiện trong evidence", "evidence": top.source_id}],
                    "calculations": [],
                    "conflicts": [],
                    "confidence": "medium" if missing else "high",
                    "evidence_used": [top.source_id],
                    "key_claims": [{"claim": top.text[:160], "evidence": top.source_id}],
                    "excluded_chunks": [
                        {"source_id": c.source_id, "reason": "Không được chọn làm bằng chứng chính"}
                        for c in chunks if c.chunk_id != top.chunk_id
                    ],
                },
            }

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

    def _agentic_analysis(self, question: str) -> dict:
        """Deterministic analysis used to exercise the Agentic RAG protocol."""
        question = question.split("Hãy phân tích", 1)[0].strip(' \"\n')
        q = question.lower()
        keywords = [
            kw for kw in (
                "nghỉ hưu", "bảo hiểm xã hội", "bảo hiểm y tế", "sổ đỏ",
                "thất nghiệp", "kết hôn", "ly hôn", "khai sinh", "đất đai",
            ) if kw in q
        ]
        if any(x in q for x in ("bao nhiêu", "mức phạt")):
            info_type = "penalty"
        elif any(x in q for x in ("tuổi", "khi nào", "bao lâu")):
            info_type = "condition"
        elif any(x in q for x in ("giấy tờ", "hồ sơ", "cần gì")):
            info_type = "list"
        else:
            info_type = "procedure"
        search = keywords or [question.strip(' \"')]
        return {
            "analysis": {
                "subject": "người dân",
                "action": "hỏi thông tin pháp lý",
                "context": question.strip(),
                "focus": keywords[0] if keywords else "pháp lý",
                "info_needed": "quy định và điều kiện",
            },
            "keywords": {"primary": keywords[:3], "secondary": keywords[3:], "legal": []},
            "search_queries": search[:3],
            "info_type": info_type,
            "extracted_facts": self._extract_facts(question),
            "missing_facts": ["giới tính"] if "nghỉ hưu" in q and not self._has_gender(question) else [],
            "ambiguity_flags": ["thiếu giới tính"] if "nghỉ hưu" in q and not self._has_gender(question) else [],
        }

    @staticmethod
    def _extract_facts(question: str) -> list[dict]:
        facts = []
        for label, pattern in (("birth_date", r"\d{1,2}/\d{1,2}/\d{4}"), ("birth_year", r"\bsinh\s+(?:năm\s+)?(?:\d{4}|\d{1,2}k\d{1,2})\b"), ("age", r"\b\d{2}\s*tuổi"), ("years", r"\b\d+\s*năm")):
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                value = match.group(0)
                if label == "birth_year":
                    year = re.search(r"(\d{4}|\d{1,2})k(\d{1,2})|(\d{4})", value, re.IGNORECASE)
                    if year and year.group(1):
                        value = str(2000 + int(year.group(2)))
                    elif year and year.group(3):
                        value = year.group(3)
                facts.append({"field": label, "value": value, "source": "user"})
        gender = re.search(r"\b(nam|nữ|nu)\b", question, re.IGNORECASE)
        if gender:
            facts.append({"field": "gender", "value": "nữ" if gender.group(1).lower() in {"nữ", "nu"} else "nam", "source": "user"})
        return facts

    @staticmethod
    def _has_gender(question: str) -> bool:
        return bool(re.search(r"\b(nam|nữ|nu)\b", question, re.IGNORECASE))

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
        # Agentic reasoning passes a large prompt containing the evidence. Use
        # only the actual question for lexical matching; otherwise frequent
        # prompt words can make an unrelated chunk look relevant.
        if "CÂU HỎI:" in query:
            query = query.split("CÂU HỎI:", 1)[1].split("\n\nEVIDENCE", 1)[0]
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
            if "nghỉ hưu" in query.lower():
                score += 8 * int("thời điểm nghỉ hưu" in text_lower or "tuổi nghỉ hưu" in text_lower)
            if "sổ đỏ" in query.lower():
                score += 8 * int("giấy chứng nhận" in text_lower or "quyền sử dụng đất" in text_lower)
            if "bảo hiểm xã hội" in query.lower():
                score += 5 * int("điều kiện" in text_lower and "lương hưu" in text_lower)
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
