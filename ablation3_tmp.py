# -*- coding: utf-8 -*-
import json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
import logging
logging.disable(logging.WARNING)
from pathlib import Path
from app.config import Settings
from app.pipeline import make_retriever
from app.retrieval.hybrid_retriever import (
    DenseIndex, _rrf_fuse, _prefer_current_sources, _expand_adjacent,
    _classify_evidence,
)

rows = [json.loads(l) for l in open("data/eval/results_1000v2_bm25.jsonl", encoding="utf-8")]
sample = [r for r in rows if r["expected_source_ids"]][:300]

bm25 = make_retriever(Settings(app_mode="cloud", retrieval_backend="bm25"))
dense = DenseIndex.from_chunks(bm25.chunks, cache_path=Path("data/chunks/real_embeddings.npz"))
hybrid = make_retriever(Settings(app_mode="cloud", retrieval_backend="hybrid"))

EV_BONUS = {"direct_answer": 0.0012, "conditions_exceptions": 0.0009,
            "procedure": 0.0006, "citation_only": 0.0003, "irrelevant": 0.0}

stats = {k: 0 for k in ["A", "B", "C", "D_notitle", "D_full"]}
lost_examples = []
t0 = time.perf_counter()
for i, r in enumerate(sample):
    q = r["question_text"]; exp = set(r["expected_source_ids"])
    b = bm25.search(q, top_k=20)
    d = dense.search(q, top_k=20)
    fused, _ = _rrf_fuse([b, d])
    def has5(lst): return any(h.source_id in exp for h in lst[:5])
    if has5(fused): stats["A"] += 1
    pref = _prefer_current_sources(fused)
    if has5(pref): stats["B"] += 1
    else:
        rank_in_A = next((j+1 for j, h in enumerate(fused) if h.source_id in exp), None)
        lost_examples.append((r, rank_in_A, [h.source_id for h in pref[:3]]))
    expd = _expand_adjacent(pref, bm25.chunks, q)
    if has5(expd): stats["C"] += 1
    rescored = []
    for h in expd:
        tb = hybrid._title_boost(q, h.source_id)
        rescored.append((h.score + tb + EV_BONUS.get(_classify_evidence(q, h), 0.0), tb > 0, h))
    rescored.sort(key=lambda p: (-p[0], p[2].chunk_id))
    if any(h.source_id in exp for _, _, h in rescored[:5]): stats["D_full"] += 1
    rescored_nt = sorted(((h.score + EV_BONUS.get(_classify_evidence(q, h), 0.0), False, h) for h in expd),
                         key=lambda p: (-p[0], p[2].chunk_id))
    if any(h.source_id in exp for _, _, h in rescored_nt[:5]): stats["D_notitle"] += 1
    if (i+1) % 100 == 0: print(f"..{i+1}", flush=True)

n = len(sample)
for k in ["A", "B", "C", "D_notitle", "D_full"]:
    print(f"{k:<12} hit@5={stats[k]/n:.1%}")
print(f"total {time.perf_counter()-t0:.0f}s")
print("\nLost-in-B examples (rank in A -> gone after prefer_current):")
for r, pos, top in lost_examples[:10]:
    print(f"  A_rank={pos} exp={r['expected_source_ids']} B_top={top} | {r['question_text'][:60]!r}")
