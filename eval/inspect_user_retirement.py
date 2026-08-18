#!/usr/bin/env python3
"""Inspect one personalized retirement query without using the FAQ path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.config import Settings
from app.pipeline import Pipeline


QUERY = "khi nao toi đc nghỉ hưu, tôi là nam sinh 2k2"


def main() -> int:
    pipeline = Pipeline(settings=Settings(app_mode="mock", retrieval_backend="bm25", llm_backend="mock", tts_backend="mock"))
    captured = {}
    original_analyze = pipeline.agentic_retriever.analyze_query
    original_reason = pipeline.agentic_reasoner.reason

    def analyze(query):
        result = original_analyze(query)
        captured["analysis"] = result
        return result

    def reason(query, chunks):
        result = original_reason(query, chunks)
        captured["reasoning"] = result
        captured["chunks"] = chunks
        return result

    pipeline.agentic_retriever.analyze_query = analyze
    pipeline.agentic_reasoner.reason = reason
    session = pipeline.create_session()
    result = pipeline.process_text(session, QUERY)
    analysis = captured.get("analysis")
    reasoning = captured.get("reasoning")

    print("QUERY:", QUERY)
    print("FAQ_ANSWERED:", result.faq_answered or "NO")
    print("DECISION:", result.decision.zone.value, result.decision.action.value)
    print("REASON_CODES:", result.decision.reason_codes)
    print("\nANALYSIS:")
    if analysis:
        print(json.dumps({
            "focus": analysis.focus,
            "info_type": analysis.info_type,
            "search_queries": analysis.search_queries,
            "extracted_facts": analysis.extracted_facts,
            "missing_facts": analysis.missing_facts,
            "ambiguity_flags": analysis.ambiguity_flags,
        }, ensure_ascii=False, indent=2))
    else:
        print("NOT_CALLED")
    print("\nEVIDENCE:")
    for chunk in captured.get("chunks", []):
        print(f"- {chunk.source_id} score={chunk.score:.3f}: {chunk.text[:260].replace(chr(10), ' ')}")
    print("\nSTRUCTURED_REASONING:")
    if reasoning:
        print(json.dumps({
            "extracted_facts": reasoning.extracted_facts,
            "missing_facts": reasoning.missing_facts,
            "applicable_rules": reasoning.applicable_rules,
            "calculations": reasoning.calculations,
            "conflicts": reasoning.conflicts,
            "confidence": reasoning.confidence,
            "evidence_used": reasoning.evidence_used,
            "key_claims": reasoning.key_claims,
        }, ensure_ascii=False, indent=2))
    else:
        print("NOT_CALLED")
    print("\nANSWER:")
    print(result.answer.answer_text if result.answer else "NO ANSWER")
    print("\nSOURCES:", result.answer.source_ids if result.answer else [])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
