import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
from sentence_transformers import SentenceTransformer

from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.document_loader import DocumentLoader

_QUERY_PREFIX = "query: "
_BM25_GATE = 12.2
_DENSE_GATE = 0.84


def main():
    questions = [json.loads(l) for l in open("data/eval/gen_1k_clean.jsonl", encoding="utf-8")]
    wg = [q for q in questions if q.get("expected_source_ids") and q.get("source_chunk_id")]
    chunk_recs = DocumentLoader.load_chunks("data/chunks/real_chunks.jsonl")
    bm = BM25Retriever.from_chunks(chunk_recs)
    model = SentenceTransformer("intfloat/multilingual-e5-small")
    emb = np.load("data/chunks/real_embeddings.npz", allow_pickle=True)
    emb_ids = list(emb["ids"])
    emb_arr = emb["embeddings"]

    def eval_variant(name, top_k, pool):
        r1 = r3 = r5 = 0
        mrr = 0.0
        gated = 0
        for q in wg:
            expected = q.get("expected_source_ids") or []
            bm_hits = bm.search(q["question_text"], top_k=pool)
            qv = model.encode([_QUERY_PREFIX + q["question_text"]], normalize_embeddings=True)[0]
            sims = emb_arr @ qv
            order = np.argsort(-sims)[:pool]
            dense_ids = [(emb_ids[i], float(sims[i])) for i in order if sims[i] > 0]
            if (not bm_hits or bm_hits[0].score < _BM25_GATE) and (not dense_ids or dense_ids[0][1] < _DENSE_GATE):
                gated += 1
                continue
            merged = defaultdict(list)
            for rank, h in enumerate(bm_hits):
                merged[h.chunk_id].append(rank)
            for rank, (cid, _sc) in enumerate(dense_ids):
                merged[cid].append(rank)
            ranked = sorted(merged.items(), key=lambda kv: -sum(1.0 / (60 + r + 1) for r in kv[1]))
            ids = [cid for cid, _ in ranked][:top_k]
            rec = [any(exp in cid for exp in expected) for cid in ids]
            if any(rec):
                r1 += int(rec[0])
                r3 += int(any(rec[:3]))
                r5 += int(any(rec[:5]))
                mrr += 1.0 / (rec.index(True) + 1)
        n = len(wg)
        print(name, "| rec@1", round(r1 / n, 3), "| rec@3", round(r3 / n, 3),
              "| rec@5", round(r5 / n, 3), "| MRR", round(mrr / n, 3), "| gated", gated)

    t0 = time.perf_counter()
    eval_variant("baseline top5 pool20", 5, 20)
    print("  sec:", round(time.perf_counter() - t0, 1))
    t0 = time.perf_counter()
    eval_variant("top10   pool40", 10, 40)
    print("  sec:", round(time.perf_counter() - t0, 1))
    t0 = time.perf_counter()
    eval_variant("top5    pool40", 5, 40)
    print("  sec:", round(time.perf_counter() - t0, 1))


if __name__ == "__main__":
    main()