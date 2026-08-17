import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))
import numpy as np

from app.config import load_settings
from app.pipeline import make_retriever
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.document_loader import DocumentLoader

chunks = {}
for l in open("data/chunks/real_chunks.jsonl", encoding="utf-8"):
    c = json.loads(l)
    chunks[c["chunk_id"]] = c.get("text", "")

emb = np.load("data/chunks/real_embeddings.npz", allow_pickle=True)
emb_ids = list(emb["ids"])
emb_arr = emb["embeddings"]
print("emb shape:", emb_arr.shape)

import app.retrieval.hybrid_retriever as hr
print("HR _QUERY_PREFIX:", repr(hr._QUERY_PREFIX), "| _EMB_MODEL:", hr._EMB_MODEL)

from sentence_transformers import SentenceTransformer
model = SentenceTransformer(hr._EMB_MODEL)
chunk_recs = DocumentLoader.load_chunks("data/chunks/real_chunks.jsonl")
bm = BM25Retriever.from_chunks(chunk_recs)

s = load_settings()
rt = make_retriever(s)

questions = [json.loads(l) for l in open("data/eval/gen_1k_clean.jsonl", encoding="utf-8")]
wg = [q for q in questions if q.get("expected_source_ids") and q.get("source_chunk_id")]

for q in wg[:5]:
    qt = q["question_text"]
    real_hits = rt.search(qt, top_k=5)
    real_ids = [h.chunk_id for h in real_hits]
    bm_hits = bm.search(qt, top_k=20)
    qv = model.encode([hr._QUERY_PREFIX + qt], normalize_embeddings=True)[0]
    sims = emb_arr @ qv
    order = np.argsort(-sims)[:20]
    dense_ids = [emb_ids[i] for i in order if sims[i] > 0]
    print("Q:", qt[:60])
    print("  real  :", real_ids[:5])
    print("  bm25  :", [h.chunk_id for h in bm_hits][:5])
    print("  dense :", dense_ids[:5])
    print("  gold  :", q["source_chunk_id"])