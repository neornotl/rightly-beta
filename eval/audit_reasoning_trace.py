#!/usr/bin/env python3
"""Audit only structured, non-sensitive reasoning metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from app.config import Settings
from app.pipeline import Pipeline


QUERIES = [
    "Tôi sinh ngày 24/09/2000, khi nào được nghỉ hưu?",
    "Tôi đóng bảo hiểm xã hội 18 năm, năm nay 55 tuổi có được nghỉ hưu chưa?",
    "Đất nhà tôi chưa có sổ đỏ, muốn làm lần đầu cần giấy tờ gì?",
    "Hàng xóm mở nhạc lớn mỗi đêm, tôi phải xử lý thế nào?",
    "Ngày mai ở Hà Nội có mưa không?",
]


def main() -> int:
    pipeline = Pipeline(settings=Settings(app_mode="mock", retrieval_backend="bm25", llm_backend="mock", tts_backend="mock"))
    original_analyze = pipeline.agentic_retriever.analyze_query
    original_reason = pipeline.agentic_reasoner.reason
    traces = {}

    def analyze(query):
        result = original_analyze(query)
        traces.setdefault(query, {})["analysis"] = {
            "subject": result.subject,
            "action": result.action,
            "context": result.context,
            "focus": result.focus,
            "info_needed": result.info_needed,
            "primary_keywords": result.primary_keywords,
            "secondary_keywords": result.secondary_keywords,
            "legal_keywords": result.legal_keywords,
            "search_queries": result.search_queries,
            "info_type": result.info_type,
        }
        return result

    def reason(query, chunks):
        result = original_reason(query, chunks)
        traces.setdefault(query, {})["reasoning"] = {
            "retrieved": [{"source_id": c.source_id, "chunk_id": c.chunk_id, "score": c.score, "text": c.text[:240]} for c in chunks],
            "evidence_used": result.evidence_used,
            "key_claims": result.key_claims,
            "excluded_chunks": result.excluded_chunks,
            "answer_source_ids": result.source_ids,
            "extracted_facts": result.extracted_facts,
            "missing_facts": result.missing_facts,
            "applicable_rules": result.applicable_rules,
            "calculations": result.calculations,
            "conflicts": result.conflicts,
            "confidence": result.confidence,
        }
        return result

    pipeline.agentic_retriever.analyze_query = analyze
    pipeline.agentic_reasoner.reason = reason
    session = pipeline.create_session()

    for query in QUERIES:
        result = pipeline.process_text(session, query)
        print("\n" + "=" * 88)
        print(f"QUERY: {query}")
        print(f"DECISION: {result.decision.zone.value}/{result.decision.action.value}")
        trace = traces.get(query, {})
        print("ANALYSIS:")
        print(json.dumps(trace.get("analysis", "NOT_CALLED"), ensure_ascii=False, indent=2))
        print("REASONING AUDIT:")
        print(json.dumps(trace.get("reasoning", "NOT_CALLED"), ensure_ascii=False, indent=2))
        if result.answer:
            print("ANSWER:")
            print(result.answer.answer_text[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
