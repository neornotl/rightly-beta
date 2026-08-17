"""Retrieval tests: BM25 on demo data, sufficiency, no invented citations."""

from __future__ import annotations

from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.document_loader import DocumentLoader


def _retriever(tmp_path) -> BM25Retriever:
    loader = DocumentLoader(sources_dir="data/sources", chunks_dir=tmp_path)
    loader.ingest()
    return BM25Retriever.from_jsonl(tmp_path / "demo_chunks.jsonl")


def test_retrieval_returns_demo_source(tmp_path):
    retriever = _retriever(tmp_path)
    results = retriever.search("Thủ tục cấp giấy xác nhận hộ khẩu tại xã Bình Minh?", top_k=5)
    assert results
    assert results[0].source_id == "demo_binhminh_procedures"
    assert all(c.source_id == "demo_binhminh_procedures" for c in results)


def test_chunks_are_labeled_demo(tmp_path):
    retriever = _retriever(tmp_path)
    results = retriever.search("khai sinh", top_k=3)
    assert results
    assert all(c.metadata and c.metadata.is_demo for c in results)


def test_retrieval_never_invents_source_ids(tmp_path):
    retriever = _retriever(tmp_path)
    results = retriever.search("không liên quan gì cả tới thủ tục này", top_k=5)
    known = {c.source_id for c in results}
    assert known <= {"demo_binhminh_procedures"}


def test_empty_retriever_returns_nothing():
    retriever = BM25Retriever.from_jsonl("nonexistent.jsonl")
    assert retriever.search("bất kỳ") == []


def test_retrieval_vietnamese_utf8(tmp_path):
    retriever = _retriever(tmp_path)
    results = retriever.search("đăng ký khai sinh cho con tôi", top_k=2)
    assert results[0].text and "đăng ký" in results[0].text.casefold()


def test_single_token_generic_query_returns_nothing(tmp_path):
    """Council T3: a 1-token query whose token is in >50% of the corpus
    (e.g. 'tục' -> df 3/4) must not flood back half the chunks."""
    retriever = _retriever(tmp_path)
    generic = retriever.search("tục", top_k=5)
    specific = retriever.search("khai", top_k=5)
    assert generic == []
    assert specific  # non-generic single tokens still match
