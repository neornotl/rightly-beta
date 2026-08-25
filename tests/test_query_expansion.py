from __future__ import annotations

from app.retrieval.agentic_retriever import AgenticRetriever, QueryAnalysis
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.query_expansion import expand_legal_query


def test_no_diacritic_red_light_query_gets_statutory_variants():
    variants = expand_legal_query("quy dinh khi vuot den do")
    plain = {v.casefold() for v in variants}
    assert any("không chấp hành hiệu lệnh" in v for v in variants)
    assert any("168/2024" in v for v in variants)
    assert len(variants) <= 8


def test_common_no_diacritic_legal_topic_gets_canonical_variant():
    variants = expand_legal_query("thu tuc can cuoc cong dan can giay to gi")
    assert any("căn cước công dân" in v for v in variants)


def test_agentic_retrieval_uses_expanded_no_diacritic_query(tmp_path):
    retriever = BM25Retriever.from_jsonl("data/chunks/real_chunks.jsonl")

    class FailingLLM:
        def generate_answer(self, *args, **kwargs):
            raise RuntimeError("analysis unavailable")

    agent = AgenticRetriever(FailingLLM(), retriever, top_k=5)
    chunks = agent.retrieve("quy dinh khi vuot den do")
    assert chunks
    assert chunks[0].source_id == "nd168_2024"
