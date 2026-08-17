import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))
import numpy as np

chunks = {}
for l in open("data/chunks/real_chunks.jsonl", encoding="utf-8"):
    c = json.loads(l)
    chunks[c["chunk_id"]] = c.get("text", "")

emb = np.load("data/chunks/real_embeddings.npz", allow_pickle=True)
ids = list(emb["ids"])
print("npz ids:", len(ids), "| first:", ids[:3], "| type:", type(ids[0]))
ck_ids = [k for k in chunks.keys()]
print("chunks ids:", len(ck_ids), "| first:", ck_ids[:3])
miss = [i for i in ids if i not in chunks]
print("npz ids not in chunks dict:", len(miss), miss[:3])

questions = [json.loads(l) for l in open("data/eval/gen_1k_clean.jsonl", encoding="utf-8")]
wg = [q for q in questions if q.get("expected_source_ids") and q.get("source_chunk_id")]
print("wg:", len(wg))
for q in wg[:3]:
    print("Q:", q["question_text"][:80], "| gold:", q["source_chunk_id"])
    print("   gold in npz ids:", q["source_chunk_id"] in set(ids))