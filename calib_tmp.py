# -*- coding: utf-8 -*-
"""Fast iteration harness: load retrievers once, score variants on a sample."""
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
grounded = [r for r in rows if r["expected_source_ids"]][:300]
adv_all = [r for r in rows if not r["expected_source_ids"]]
print(f"sample grounded={len(grounded)} adv={len(adv_all)}")

t0 = time.perf_counter()
bm25 = make_retriever(Settings(app_mode="cloud", retrieval_backend="bm25"))
dense = DenseIndex.from_chunks(bm25.chunks, cache_path=Path("data/chunks/real_embeddings.npz"))
hybrid = make_retriever(Settings(app_mode="cloud", retrieval_backend="hybrid"))
print(f"loaded in {time.perf_counter()-t0:.0f}s")

def hit5(fn, data):
    n = 0
    for r in data:
        got = [h.source_id for h in fn(r["question_text"])][:5]
        if any(s in set(r["expected_source_ids"]) for s in got):
            n += 1
    return n / len(data)

t0 = time.perf_counter()
print(f"NEW production hybrid hit@5 (300q): {hit5(hybrid.search, grounded):.1%}  ({(time.perf_counter()-t0)/len(grounded)*1000:.0f}ms/q)")

# score distributions for gate calibration
import statistics as st
g_scores, a_scores = [], []
for r in grounded:
    b = bm25.search(r["question_text"], top_k=1)
    d = dense.search(r["question_text"], top_k=1)
    g_scores.append((b[0].score if b else 0.0, d[0].score if d else 0.0))
for r in adv_all:
    b = bm25.search(r["question_text"], top_k=1)
    d = dense.search(r["question_text"], top_k=1)
    a_scores.append((b[0].score if b else 0.0, d[0].score if d else 0.0))

def q(vals, p):
    vals = sorted(vals)
    return vals[int(p * (len(vals) - 1))]

gb = [x[0] for x in g_scores]; gd_ = [x[1] for x in g_scores]
ab = [x[0] for x in a_scores]; ad = [x[1] for x in a_scores]
print("\nBM25 top1 score: grounded p05/p50 =", round(q(gb,.05),1), round(q(gb,.5),1),
      "| adversarial p50/p95 =", round(q(ab,.5),1), round(q(ab,.95),1))
print("Dense top1 score: grounded p05/p50 =", round(q(gd_,.05),3), round(q(gd_,.5),3),
      "| adversarial p50/p95 =", round(q(ad,.5),3), round(q(ad,.95),3))

best = None
for B in range(20, 80, 5):
    refused_g = sum(1 for x in gb if x < B)
    caught_a = sum(1 for x in ab if x < B)
    print(f"  gate_bm25={B}: wrongly_refuse {refused_g/len(gb):.0%} of grounded | catch {caught_a/len(ab):.0%} of adv")
