"""Agentic Retrieval: LLM-driven query analysis and search query generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from app.llm.base import BaseLLM
from app.llm.prompts import AGENTIC_RETRIEVAL_SYSTEM, AGENTIC_REASONING_SYSTEM
from app.retrieval.base import Retriever
from app.schemas import RetrievedChunk
from app.retrieval.query_expansion import expand_legal_query, strip_diacritics


@dataclass
class QueryAnalysis:
    """LLM's analysis of the user query."""
    subject: str
    action: str
    context: str
    focus: str
    info_needed: str
    primary_keywords: list[str]
    secondary_keywords: list[str]
    legal_keywords: list[str]
    search_queries: list[str]
    info_type: str  # table|list|procedure|condition|penalty|deadline|agency
    extracted_facts: list[dict] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    ambiguity_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "action": self.action,
            "context": self.context,
            "focus": self.focus,
            "info_needed": self.info_needed,
            "primary_keywords": list(self.primary_keywords),
            "secondary_keywords": list(self.secondary_keywords),
            "legal_keywords": list(self.legal_keywords),
            "search_queries": list(self.search_queries),
            "info_type": self.info_type,
            "extracted_facts": list(self.extracted_facts),
            "missing_facts": list(self.missing_facts),
            "ambiguity_flags": list(self.ambiguity_flags),
        }


@dataclass
class ReasoningResult:
    """LLM's reasoning over retrieved chunks."""
    answer_text: str
    spoken_citation: str
    source_ids: list[str]
    limitations: list[str]
    next_step: str
    evidence_used: list[str]
    key_claims: list[dict]
    excluded_chunks: list[dict]
    extracted_facts: list[dict] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    applicable_rules: list[dict] = field(default_factory=list)
    calculations: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    confidence: str = "low"


class AgenticRetriever:
    """LLM-driven retrieval: LLM analyzes query, generates search queries, retrieves, then reasons."""
    
    def __init__(
        self,
        llm: BaseLLM,
        retriever: Retriever,
        top_k: int = 5,
        max_search_queries: int = 3,
    ):
        self.llm = llm
        self.retriever = retriever
        self.top_k = top_k
        self.max_search_queries = max_search_queries
        self.last_analysis: Optional[QueryAnalysis] = None
    
    def analyze_query(self, query: str) -> QueryAnalysis:
        """Step 1: LLM analyzes query and generates search queries."""
        user_prompt = f"""Câu hỏi của người dân: "{query}"

Hãy phân tích và sinh ra JSON theo schema bên trên."""
        
        try:
            response = self.llm.generate_answer(
                query=user_prompt,
                chunks=[],  # No chunks needed for analysis
                max_chars=2000,
                history=None,
                system_prompt=AGENTIC_RETRIEVAL_SYSTEM,
            )
            # The LLM should return JSON with analysis and search_queries.
            # Backends differ in shape: MockLLM wraps the JSON in
            # {"answer_text": "<json>"}; Pateway/Groq parse it and return the
            # analysis dict directly. Normalize both to the analysis dict.
            if isinstance(response, dict) and isinstance(response.get("answer_text"), str):
                parsed = json.loads(response["answer_text"])
            elif isinstance(response, dict):
                parsed = response
            else:
                parsed = json.loads(str(response))
            
            analysis = parsed.get("analysis", {})
            keywords = parsed.get("keywords", {})
            search_queries = parsed.get("search_queries", [])
            info_type = parsed.get("info_type", "procedure")
            
            return QueryAnalysis(
                subject=analysis.get("subject", ""),
                action=analysis.get("action", ""),
                context=analysis.get("context", ""),
                focus=analysis.get("focus", ""),
                info_needed=analysis.get("info_needed", ""),
                primary_keywords=keywords.get("primary", []),
                secondary_keywords=keywords.get("secondary", []),
                legal_keywords=keywords.get("legal", []),
                search_queries=search_queries[:3],  # max 3
                info_type=info_type,
                extracted_facts=parsed.get("extracted_facts", []),
                missing_facts=parsed.get("missing_facts", []),
                ambiguity_flags=parsed.get("ambiguity_flags", []),
            )
        except Exception as e:
            # Fallback: simple keyword extraction
            return self._fallback_analysis(query)
    
    def _fallback_analysis(self, query: str) -> QueryAnalysis:
        """Simple fallback when LLM analysis fails."""
        q_lower = query.lower()
        q_plain = strip_diacritics(query)
        
        # Detect info type
        if any(w in q_lower for w in ["bao nhiêu", "mức phạt", "phạt"]) or "phat" in q_plain:
            info_type = "penalty"
        elif any(w in q_lower for w in ["tuổi", "khi nào", "năm nào"]):
            info_type = "table"
        elif any(w in q_lower for w in ["hồ sơ", "giấy tờ", "cần gì"]):
            info_type = "list"
        elif any(w in q_lower for w in ["điều kiện", "được không", "ai được"]) or any(
            w in q_plain for w in ["dieu kien", "duoc khong", "ai duoc"]
        ):
            info_type = "condition"
        elif any(w in q_lower for w in ["thủ tục", "làm sao", "nơi nộp", "thời hạn"]):
            info_type = "procedure"
        elif any(w in q_lower for w in ["cơ quan", "ở đâu", "nơi nào"]):
            info_type = "agency"
        else:
            info_type = "procedure"
        
        # Extract simple keywords
        keywords = []
        for kw in ["nghỉ hưu", "vượt đèn đỏ", "khai sinh", "kết hôn", "ly hôn", "hộ chiếu", "căn cước", "sổ đỏ", "thừa kế", "bảo hiểm", "phạt", "hồ sơ", "giấy tờ", "điều kiện", "tuổi", "mức phạt", "thời hạn", "thủ tục"]:
            if kw in q_lower:
                keywords.append(kw)

        # Keep the fallback useful when the input has no Vietnamese tone
        # marks (a common keyboard and speech-recognition form).
        if re.search(r"\bvuot\s+den\s+do\b|\bden\s+do\b", q_plain):
            keywords.extend(["vượt đèn đỏ", "không chấp hành hiệu lệnh đèn tín hiệu"])
        
        # Build search query
        search_query = " ".join(keywords[:5]) if keywords else query
        
        return QueryAnalysis(
            subject="người dân",
            action="hỏi thông tin",
            context=query,
            focus=keywords[0] if keywords else "thông tin pháp lý",
            info_needed="thông tin pháp lý",
            primary_keywords=keywords[:3],
            secondary_keywords=keywords[3:],
            legal_keywords=[],
            search_queries=[search_query],
            info_type=info_type,
            extracted_facts=[],
            missing_facts=[],
            ambiguity_flags=[],
        )
    
    def retrieve(self, query: str, analysis: Optional[QueryAnalysis] = None) -> list[RetrievedChunk]:
        """Agentic retrieval: LLM analyzes → generates queries → retrieves → merges."""
        # Step 1: LLM analyzes query
        analysis = analysis or self.analyze_query(query)
        self.last_analysis = analysis
        
        # Step 2: Retrieve with each search query.  The LLM is still the
        # semantic planner, but every query gets a bounded deterministic
        # expansion so no-diacritic speech/keyboard input reaches the legal
        # phrase used by the corpus (for example "vuot den do").
        all_chunks = []
        seen_chunk_ids = set()

        candidate_queries: list[str] = []
        seen_queries: set[str] = set()
        for raw_query in [*analysis.search_queries, query]:
            for sq in expand_legal_query(raw_query):
                key = strip_diacritics(sq)
                if key and key not in seen_queries:
                    seen_queries.add(key)
                    candidate_queries.append(sq)
        # Keep latency bounded even if a backend returns a very long list.
        for sq in candidate_queries[: max(self.max_search_queries * 3, 6)]:
            chunks = self.retriever.search(sq, top_k=max(self.top_k, 8))
            for chunk in chunks:
                if chunk.chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(chunk.chunk_id)
                    all_chunks.append(chunk)

        # Sort by score, limit to top_k
        all_chunks.sort(key=lambda c: c.score, reverse=True)
        return all_chunks[:self.top_k]


class AgenticReasoner:
    """LLM reasons over retrieved chunks to produce final answer."""
    
    def __init__(self, llm: BaseLLM):
        self.llm = llm
        self.query_analysis: Optional[QueryAnalysis] = None
    
    def reason(self, query: str, chunks: list[RetrievedChunk]) -> ReasoningResult:
        """Step 2: LLM reasons over retrieved chunks and produces answer.
        
        Compatible with standard LLM interface (returns dict with fields directly).
        """
        # Build evidence text
        evidence_text = "\n\n".join(
            f"[source_id={c.source_id}|chunk_id={c.chunk_id}]\n{c.text}"
            for c in chunks
        )
        
        analysis_text = ""
        if self.query_analysis is not None:
            analysis_text = f"""
QUERY ANALYSIS (đã trích xuất, cần kiểm tra lại):
{json.dumps({
    "subject": self.query_analysis.subject,
    "action": self.query_analysis.action,
    "context": self.query_analysis.context,
    "focus": self.query_analysis.focus,
    "info_needed": self.query_analysis.info_needed,
    "primary_keywords": self.query_analysis.primary_keywords,
    "secondary_keywords": self.query_analysis.secondary_keywords,
    "legal_keywords": self.query_analysis.legal_keywords,
    "search_queries": self.query_analysis.search_queries,
    "facts": self.query_analysis.extracted_facts,
    "missing_facts": self.query_analysis.missing_facts,
    "ambiguity_flags": self.query_analysis.ambiguity_flags,
    "info_type": self.query_analysis.info_type,
}, ensure_ascii=False)}
"""
        user_prompt = f"""CÂU HỎI: {query}
{analysis_text}

EVIDENCE (các đoạn văn bản pháp luật được cung cấp):
{evidence_text}

Hãy suy luận và trả lời theo JSON schema. Nội dung answer_text bắt buộc theo đúng bố cục sau:
1. Mở đầu lịch sự bằng "Dạ," rồi đưa kết luận trực tiếp trong 1-2 câu.
2. "Căn cứ và giải thích:" — xuống dòng, liệt kê rules/điều kiện/phép tính bằng "- "; phải ghi rõ tên loại văn bản, số/ký hiệu và Điều/Khoản nếu evidence cung cấp.
3. Sau mỗi quy định, giải thích ngắn quy định đó có nghĩa gì với trường hợp người hỏi. Thuật ngữ pháp lý phải được giải thích bằng từ đời thường.
4. Nếu có nhiều điều kiện hoặc bước làm, tách thành các mục/gạch đầu dòng, mỗi ý chỉ một việc.
5. "Kết luận:" — chốt lại kết quả và giới hạn trong 1-2 câu.
Trả lời đủ ý, thường khoảng 120-350 từ tùy độ phức tạp (đây không phải giới hạn cứng), không cắt ngang câu hoặc kết thúc bằng dấu ba chấm.
Không chào xã giao dài dòng, không nhắc lại câu hỏi, không đưa ví dụ trong văn bản thành facts của người dân.
{{
  "answer_text": "string",
  "spoken_citation": "string", 
  "source_ids": ["string"],
  "limitations": ["string"],
  "next_step": "string",
  "reasoning": {{
    "extracted_facts": [{{"field": "string", "value": "string", "source": "user|evidence"}}],
    "missing_facts": ["string"],
    "applicable_rules": [{{"rule": "string", "evidence": "source_id"}}],
    "calculations": [{{"expression": "string", "result": "string", "evidence": "source_id"}}],
    "conflicts": [{{"issue": "string", "sources": ["source_id"], "resolution": "string"}}],
    "confidence": "high|medium|low",
    "evidence_used": ["source_id"],
    "key_claims": [{{"claim": "string", "evidence": "source_id"}}],
    "excluded_chunks": [{{"source_id": "string", "reason": "string"}}]
  }}
}}"""
        
        try:
            response = self.llm.generate_answer(
                query=user_prompt,
                chunks=chunks,
                max_chars=4000,
                history=None,
                system_prompt=AGENTIC_REASONING_SYSTEM,
            )
            
            # Standard LLM interface returns dict with fields directly
            # New agentic format: answer_text contains JSON string
            # Handle both formats
            if isinstance(response, dict):
                # Standard format: response has fields directly
                parsed = response
            elif isinstance(response, str):
                # String response, try to parse as JSON
                try:
                    parsed = json.loads(response)
                except json.JSONDecodeError:
                    # Fallback: treat as plain text answer
                    return self._fallback_reasoning(query, chunks)
            else:
                return self._fallback_reasoning(query, chunks)
            
            # Extract source_ids - handle both list and comma-separated string
            source_ids = parsed.get("source_ids", [])
            if isinstance(source_ids, str):
                source_ids = [s.strip() for s in source_ids.split(",") if s.strip()]
            elif not isinstance(source_ids, list):
                source_ids = []

            def _norm(sid: str) -> str:
                # LLM may echo the full marker "[source_id=X|chunk_id=Y]" or
                # "X|chunk_id=Y"; reduce to the bare source_id for validation.
                sid = str(sid).strip()
                if "|chunk_id=" in sid:
                    sid = sid.split("|chunk_id=", 1)[0]
                if sid.startswith("source_id="):
                    sid = sid[len("source_id="):]
                return sid.strip()

            source_ids = [_norm(s) for s in source_ids]
            reasoning = parsed.get("reasoning", {}) or {}
            evidence_used = [_norm(s) for s in reasoning.get("evidence_used", [])]
            key_claims = [
                {**claim, "evidence": _norm(claim.get("evidence", ""))}
                for claim in reasoning.get("key_claims", [])
            ]
            missing_facts = reasoning.get("missing_facts", [])
            confidence = reasoning.get("confidence", "low")

            return ReasoningResult(
                answer_text=parsed.get("answer_text", ""),
                spoken_citation=parsed.get("spoken_citation", ""),
                source_ids=source_ids,
                limitations=parsed.get("limitations", []),
                next_step=parsed.get("next_step", ""),
                evidence_used=evidence_used,
                key_claims=key_claims,
                excluded_chunks=parsed.get("reasoning", {}).get("excluded_chunks", []),
                extracted_facts=parsed.get("reasoning", {}).get("extracted_facts", []),
                missing_facts=missing_facts,
                applicable_rules=parsed.get("reasoning", {}).get("applicable_rules", []),
                calculations=parsed.get("reasoning", {}).get("calculations", []),
                conflicts=parsed.get("reasoning", {}).get("conflicts", []),
                confidence=confidence,
            )
        except (TimeoutError, ConnectionError, ConnectionRefusedError, ConnectionResetError, OSError) as e:
            # Re-raise critical network/timeout errors for pipeline-level handling
            raise
        except Exception as e:
            # Fallback: simple answer for other errors (parsing, format, etc.)
            return self._fallback_reasoning(query, chunks)
    
    def _fallback_reasoning(self, query: str, chunks: list[RetrievedChunk]) -> ReasoningResult:
        """Simple fallback when LLM reasoning fails."""
        if not chunks:
            return ReasoningResult(
                answer_text="Dạ phần này hiện em chưa có dữ liệu chính xác trong nguồn pháp luật. Anh/chị vui lòng gọi 1022 hoặc đến UBND phường/xã nơi anh/chị sinh sống để được hướng dẫn chính xác hơn nha.",
                spoken_citation="",
                source_ids=[],
                limitations=["Không tìm thấy bằng chứng trong corpus"],
                next_step="Liên hệ 1022 hoặc UBND cấp xã",
                evidence_used=[],
                key_claims=[],
                excluded_chunks=[],
                confidence="low",
            )
        
        # Use first chunk
        chunk = chunks[0]
        return ReasoningResult(
            answer_text=f"Dạ vâng ạ. Theo {chunk.source_id} thì {chunk.text[:200]}...",
            spoken_citation=f"Theo {chunk.source_id}",
            source_ids=[chunk.source_id],
            limitations=["Đây là dữ liệu DEMO, không phải hướng dẫn chính thức."],
            next_step="Anh/chị cần em giải thích thêm phần nào không ạ?",
            evidence_used=[chunk.source_id],
            key_claims=[{"claim": chunk.text[:100], "evidence": chunk.source_id}],
            excluded_chunks=[],
            confidence="low",
        )
