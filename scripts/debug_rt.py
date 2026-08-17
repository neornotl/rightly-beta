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
for q in wg[:5]:
    hits = rt.search(q["question_text"], top_k=5)
    ids = [h.chunk_id for h in hits]
    print("Q:", q["question_text"][:70])
    print("  gold:", q["source_chunk_id"], "| hit5:", q["source_chunk_id"] in ids)
    print("  ids:", ids[:5])