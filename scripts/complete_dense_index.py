"""Resume building the real-corpus dense embedding cache."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval.document_loader import DocumentLoader
from app.retrieval.hybrid_retriever import DenseIndex


chunks = DocumentLoader.load_chunks("data/chunks/real_chunks.jsonl")
DenseIndex.from_chunks(chunks, cache_path="data/chunks/real_embeddings.npz")
print("DENSE COMPLETE", flush=True)
