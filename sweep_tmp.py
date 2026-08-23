# -*- coding: utf-8 -*-
"""Fusion parameter sweep on family-hit@5 (300-question sample)."""
import json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
import logging
logging.disable(logging.WARNING)
from pathlib import Path
from app.config import Settings
from app.pipeline import make_retriever
from app.retrieval.hybrid_retriever import DenseIndex

rows = [json.loads(l) for l in open("data/eval/results_1000v2_bm25.jsonl", encoding="utf-8")]
sample = [r for r in rows if r["expected_source_ids"]][:300]
fam = {r["question_id"]: set(r.get("expected_family_sources") or []) | set(r["expected_source_ids"]) for r in sample}

bm25 = make_retriever(Settings(app_mode="cloud", retrieval_backend="bm25"))
dense = DenseIndex.from_chunks(bm25.chunks, cache_path=Path("data/chunks/real_embeddings.npz"))

# cache pools once
pools = {}
t0 = time.perf_counter()
for r in sample:
    q = r["question_text"]
    pools[q] = (bm25.search(q, top_k=32), dense.search(q, top_k=32))
print(f"pools cached in {time.perf_counter()-t0:.0f}s")

def rrf(lists, k=60, weights=None):
    weights = weights or [1.0] * len(lists)
    scores, order = {}, {}
    for i, hits in enumerate(lists):
        w = weights[i]
        for rank, h in enumerate(hits):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + w / (k + rank + 1)
            order.setdefault(h.chunk_id, h)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return [order[cid] for cid, _ in ranked]

def famhit(fn):
    n = 0
    for r in sample:
        got = [h.source_id for h in fn(r["question_text"])][:5]
        if any(s in fam[r["question_id"]] for s in got):
            n += 1
    return n / len(sample)

for k in (30, 60):
    for wd in (1.0, 1.15, 1.3):
        f = famhit(lambda q: rrf([pools[q][0], pools[q][1]], k=k, weights=[1.0, wd]))
        print(f"k={k} w_dense={wd}: family_hit@5={f:.1%}")
