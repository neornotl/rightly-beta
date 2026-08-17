import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from app.config import load_settings
from app.pipeline import make_retriever

s = load_settings()
rt = make_retriever(s)

questions = [json.loads(l) for l in open("data/eval/gen_1k_clean.jsonl", encoding="utf-8")]
wg = [q for q in questions if q.get("expected_source_ids") and q.get("source_chunk_id")]
print("wg:", len(wg))

for lo, hi in [(0, 150), (150, 300), (300, 450), (450, 675)]:
    sub = wg[lo:hi]
    r1 = r5 = 0
    for q in sub:
        hits = rt.search(q["question_text"], top_k=5)
        ids = [h.chunk_id for h in hits]
        gold = q["source_chunk_id"]
        if gold in ids[:1]:
            r1 += 1
        if gold in ids:
            r5 += 1
    print(f"[{lo}:{hi}] n={len(sub)} recall@1={r1/len(sub):.3f} recall@5={r5/len(sub):.3f}")