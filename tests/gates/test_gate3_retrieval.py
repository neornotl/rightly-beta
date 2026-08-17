"""GATE 3 — Retrieval on real-language questions (Luna gate #3).

Checks BM25 on the real 33k-chunk legal corpus against the 50-FAQ set:

- recall@5: the top-5 results must contain at least one chunk from a FAQ's
  own source_ids (currently 44/50 = 88%).
- corpus coverage: every FAQ source_id must actually exist in the corpus —
  a FAQ that cites a law the corpus cannot retrieve will be refused at
  runtime (documented gap for the 6 missing FAQs).

Measured threshold: recall@5 >= 80% is the gate bar; 100% is the stretch.
"""

from __future__ import annotations

import json
from pathlib import Path


def _faqs() -> list[dict]:
    data = json.loads(Path("data/faq.json").read_text(encoding="utf-8"))
    return data["faqs"] if isinstance(data, dict) else data


def _source_ids_in_corpus(bm25_retriever) -> set[str]:
    return {c.source_id for c in bm25_retriever.chunks}


def test_gate3_recall_at_5_min_80_percent(bm25_retriever):
    faqs = _faqs()
    scored = [(f, bm25_retriever.search(f.get("search_text") or f["question"], top_k=5)) for f in faqs]
    with_sources = [(f, r) for f, r in scored if f.get("source_ids")]
    hits = 0
    misses = []
    for f, results in with_sources:
        expected = set(f["source_ids"])
        got = {c.source_id for c in results}
        if got & expected:
            hits += 1
        else:
            misses.append(f["id"])
    recall = hits / len(with_sources)
    assert recall >= 0.80, (
        f"FAQ recall@5 = {recall:.0%} ({hits}/{len(with_sources)}) < 80%. "
        f"Missing FAQs: {misses}. Fix search_text/corpus before pilot."
    )


def test_gate3_corpus_covers_all_faq_sources(bm25_retriever):
    corpus = _source_ids_in_corpus(bm25_retriever)
    missing = sorted(
        sid for f in _faqs() for sid in (f.get("source_ids") or []) if sid not in corpus
    )
    assert not missing, (
        f"FAQ sources missing from corpus (would be refused at runtime): {missing}"
    )


def test_gate3_sources_retrievable_from_their_search_text(bm25_retriever):
    """For each FAQ, at least ONE of its sources must be retrievable."""
    unreachable = []
    for f in _faqs():
        if not f.get("source_ids"):
            continue
        results = bm25_retriever.search(f.get("search_text") or f["question"], top_k=5)
        if not ({c.source_id for c in results} & set(f["source_ids"])):
            unreachable.append(f["id"])
    assert not unreachable, f"FAQs with no retrievable source: {unreachable}"


def test_gate3_faq_matcher_covers_all_50(faq_matcher):
    assert faq_matcher.count == 50, f"FAQMatcher loaded {faq_matcher.count} (expected 50)"
    for f in _faqs():
        hit = faq_matcher.answer(f["question"])
        assert hit is not None, f"FAQMatcher cannot match its own question: {f['id']}"
