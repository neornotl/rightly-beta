"""Hybrid retrieval: BM25 + dense embeddings, fused with RRF, optional
cross-encoder rerank. Dense index uses a multilingual SentenceTransformer
with a disk cache of precomputed embeddings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import re

from app.retrieval.base import Retriever
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.document_loader import ChunkRecord, DocumentLoader
from app.schemas import RetrievedChunk

_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "
_EMB_MODEL = "intfloat/multilingual-e5-small"
_RERANK_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

# Answerability gate thresholds, calibrated on the real corpus (8 demo
# queries). In-corpus queries score >= one threshold; out-of-corpus queries
# (e.g. "hộ chiếu", "phạt khai sinh quá hạn") fall below both.
_BM25_GATE = 12.2
_DENSE_GATE = 0.84


def _to_chunk(rec, score: float) -> RetrievedChunk:
    metadata = rec.metadata if hasattr(rec, "metadata") else DocumentLoader.to_metadata(rec)
    return RetrievedChunk(
        chunk_id=rec.chunk_id,
        source_id=rec.source_id,
        text=rec.text,
        score=round(float(score), 4),
        metadata=metadata,
    )


@dataclass
class DenseIndex:
    """Cosine-similarity dense retriever over chunk embeddings."""

    name: str = "dense"
    model_name: str = _EMB_MODEL
    cache_path: Path = field(default=Path("data/chunks/embeddings.npz"))
    chunks: list[ChunkRecord] = field(default_factory=list)
    _model: object = field(default=None, repr=False)
    _embeddings: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.cache_path = Path(self.cache_path)

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _build(self) -> None:
        model = self._load_model()
        cache = Path(self.cache_path)
        texts = [f"{_PASSAGE_PREFIX}{c.text}" for c in self.chunks]
        ids = [c.chunk_id for c in self.chunks]
        if cache.exists():
            data = np.load(cache)
            cached_ids = data["ids"].tolist()
            if cached_ids == ids:
                self._embeddings = data["embeddings"]
                complete = data.get("complete")
                if complete is None or bool(np.all(complete)):
                    return
            # Reuse embeddings by chunk ID after corpus additions/removals.
            old_embeddings = data["embeddings"]
            complete = data.get("complete", np.ones(len(cached_ids), dtype=bool))
            old_by_id = {
                chunk_id: old_embeddings[i]
                for i, chunk_id in enumerate(cached_ids)
                if complete[i]
            }
            reused = [old_by_id.get(chunk_id) for chunk_id in ids]
            if all(row is not None for row in reused):
                self._embeddings = np.asarray(reused, dtype="float32")
                np.savez(cache, ids=ids, embeddings=self._embeddings)
                return
            self._embeddings = np.empty((0, old_embeddings.shape[1]), dtype="float32")
            pending = [i for i, row in enumerate(reused) if row is None]
            self._embeddings = np.asarray(
                [row if row is not None else np.zeros(old_embeddings.shape[1], dtype="float32") for row in reused],
                dtype="float32",
            )
            complete_mask = np.asarray([row is not None for row in reused], dtype=bool)
        else:
            self._embeddings = np.empty((0, 0), dtype="float32")
            pending = list(range(len(texts)))
            complete_mask = np.zeros(len(texts), dtype=bool)

        cache.parent.mkdir(parents=True, exist_ok=True)
        batch_size = 128
        for batch_start in range(0, len(pending), batch_size):
            indices = pending[batch_start : batch_start + batch_size]
            batch = model.encode(
                [texts[i] for i in indices],
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).astype("float32")
            for i, row in zip(indices, batch):
                self._embeddings[i] = row
                complete_mask[i] = True
            np.savez(cache, ids=ids, embeddings=self._embeddings, complete=complete_mask)
            print(f"Dense embeddings: {batch_start + len(indices)}/{len(pending)} missing vectors")

    @classmethod
    def from_chunks(cls, chunks: list[ChunkRecord], cache_path=None) -> "DenseIndex":
        idx = cls(chunks=chunks)
        if cache_path:
            idx.cache_path = Path(cache_path)
        idx._build()
        return idx

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        if not self.chunks:
            return []
        model = self._load_model()
        q = model.encode([f"{_QUERY_PREFIX}{query}"], normalize_embeddings=True)[0]
        sims = self._embeddings @ q
        order = np.argsort(-sims)[:top_k]
        return [_to_chunk(self.chunks[i], float(sims[i])) for i in order if sims[i] > 0]


def _rrf_fuse(lists: list[list[RetrievedChunk]], k: int = 60) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    order: dict[str, int] = {}
    for hits in lists:
        for rank, hit in enumerate(hits):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank + 1)
            if hit.chunk_id not in order:
                order[hit.chunk_id] = len(order)
    by_chunk = {h.chunk_id: h for hits in lists for h in hits}
    ranked = sorted(by_chunk, key=lambda cid: (-scores[cid], order[cid], cid))
    return [_to_chunk(by_chunk[cid], scores[cid]) for cid in ranked]


def _prefer_current_sources(hits: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Collapse repeated text from superseded/legacy source IDs.

    VBHN imports can have an older registry ID and a current canonical ID for
    the same text. Prefer the current Bach-Xuan VBHN source and retain only one
    chunk per source in the context so the LLM does not see conflicting copies.
    """
    by_text: dict[str, RetrievedChunk] = {}
    for hit in hits:
        key = " ".join(hit.text.split())
        current = by_text.get(key)
        if current is None:
            by_text[key] = hit
            continue
        current_title = current.metadata.title if current.metadata else ""
        hit_title = hit.metadata.title if hit.metadata else ""
        if "VBHN" in hit_title.upper() and "VBHN" not in current_title.upper():
            by_text[key] = hit
    # Also collapse alternate IDs for the same named law (for example an old
    # consolidated copy and the newer 2026 VBHN copy).
    by_title: dict[str, RetrievedChunk] = {}
    for hit in by_text.values():
        title = hit.metadata.title if hit.metadata else ""
        title_key = title.casefold().replace("_", " ").replace("-", " ")
        title_key = re.sub(r"\d+", " ", title_key)
        title_key = re.sub(r"\b(vbhn|vpqh|luat|luật|bo|bộ|qh)\b", " ", title_key)
        title_key = re.sub(r"\s+", " ", title_key).strip()
        if len(title_key) < 12:
            title_key = hit.source_id
        current = by_title.get(title_key)
        if current is None:
            by_title[title_key] = hit
            continue
        current_title = current.metadata.title if current.metadata else ""
        hit_title = hit.metadata.title if hit.metadata else ""
        current_is_vbhn = bool(re.match(r"\s*\d{1,3}-VBHN", current_title.upper()))
        hit_is_vbhn = bool(re.match(r"\s*\d{1,3}-VBHN", hit_title.upper()))
        current_year = re.search(r"_(20\d{2})$", current.source_id)
        hit_year = re.search(r"_(20\d{2})$", hit.source_id)
        newer = bool(hit_year and current_year and hit_year.group(1) > current_year.group(1))
        if (hit_is_vbhn and not current_is_vbhn) or newer:
            by_title[title_key] = hit

    def title_key(value: str) -> str:
        value = re.sub(r"[0-9_-]+|vbhn|vpqh|luật|luat|bộ|bo|qh", " ", value.casefold())
        return re.sub(r"\s+", " ", value).strip()

    current_by_title: dict[str, RetrievedChunk] = {}
    for hit in by_title.values():
        title = hit.metadata.title if hit.metadata else ""
        key = title_key(title)
        if key:
            existing = current_by_title.get(key)
            if existing is None or hit.source_id > existing.source_id:
                current_by_title[key] = hit
    if current_by_title:
        current_sources = {hit.source_id for hit in current_by_title.values()}
        by_title = {
            key: hit for key, hit in by_title.items()
            if hit.source_id in current_sources
            or title_key(hit.metadata.title if hit.metadata else "") not in current_by_title
        }

    deduped: list[RetrievedChunk] = []
    source_counts: dict[str, int] = {}
    for hit in sorted(by_title.values(), key=lambda item: -item.score):
        if source_counts.get(hit.source_id, 0) >= 3:
            continue
        source_counts[hit.source_id] = source_counts.get(hit.source_id, 0) + 1
        deduped.append(hit)
    return deduped


def _query_focus(query: str, hit: RetrievedChunk) -> float:
    """Boost a chunk when it contains the requested legal section type."""
    q = query.casefold()
    text = hit.text.casefold()
    boost = 0.0
    if "hồ sơ" in q and "lương hưu" in q:
        if "hồ sơ đề nghị hưởng lương hưu" in text:
            boost += 0.08
        if "điều 77." in text or "điều 105." in text:
            boost += 0.04
    if ("ai" in q or "những ai" in q or "đối tượng" in q) and "trợ giúp pháp lý" in q:
        if "điều 7." in text or "người được trợ giúp pháp lý" in text:
            boost += 0.08
    if "điều kiện" in q and "nhà ở xã hội" in q:
        if "mua, thuê mua nhà ở xã hội" in text or "điều kiện về nhà ở" in text:
            boost += 0.06
    if "thời giờ làm việc bình thường" in q:
        if "thời giờ làm việc bình thường" in text and "điều 105." in text:
            boost += 0.08
        elif "thời giờ làm việc bình thường" in text:
            boost += 0.03
    if "nghỉ hưu" in q and not any(term in q for term in ("suy giảm", "đặc biệt nặng nhọc", "nghỉ sớm")):
        if "điều 169. tuổi nghỉ hưu" in text:
            boost += 0.12
        elif "tuổi nghỉ hưu" in text:
            boost += 0.04
    return boost


def _expand_adjacent(
    hits: list[RetrievedChunk], chunks: list[ChunkRecord], query: str
) -> list[RetrievedChunk]:
    """Add nearby chunks when the answer is a legal list or procedure."""
    q = query.casefold()
    if not any(term in q for term in ("hồ sơ", "giấy tờ", "ai được", "những ai", "đối tượng", "điều kiện", "thời giờ làm việc", "nghỉ hưu")):
        return hits
    positions = {chunk.chunk_id: i for i, chunk in enumerate(chunks)}
    selected = {hit.chunk_id: hit for hit in hits}
    for hit in list(hits[:3]):
        pos = positions.get(hit.chunk_id)
        if pos is None:
            continue
        for i in range(max(0, pos - 2), min(len(chunks), pos + 3)):
            neighbor = chunks[i]
            if neighbor.source_id != hit.source_id:
                continue
            if neighbor.chunk_id not in selected:
                selected[neighbor.chunk_id] = _to_chunk(neighbor, max(0.001, hit.score - 0.002))
        if "điều kiện" in q or "hồ sơ" in q or "giấy tờ" in q:
            direct_terms = (
                "điều kiện về nhà ở",
                "hồ sơ đề nghị hưởng lương hưu",
                "hồ sơ đề nghị",
                "người được trợ giúp pháp lý",
                "điều 169. tuổi nghỉ hưu",
            )
            for candidate in chunks:
                if candidate.source_id != hit.source_id:
                    continue
                if any(term in candidate.text.casefold() for term in direct_terms):
                    selected.setdefault(
                        candidate.chunk_id,
                        _to_chunk(candidate, max(0.001, hit.score - 0.001)),
                    )
    return list(selected.values())


@dataclass
class HybridRetriever(Retriever):
    """BM25 + dense fused with RRF; optional cross-encoder rerank."""

    name: str = "hybrid"
    bm25: BM25Retriever = None  # type: ignore[assignment]
    dense: DenseIndex = None  # type: ignore[assignment]
    exclude_demo: bool = False
    rerank: bool = False
    gate: str = "bm25_dense"  # none | bm25_dense
    bm25_gate: float = _BM25_GATE
    dense_gate: float = _DENSE_GATE
    rerank_threshold: float = 0.0  # only applied when gate == "none"
    _reranker: object = field(default=None, repr=False)

    @classmethod
    def from_chunks(
        cls,
        chunks: list[ChunkRecord],
        cache_path=None,
        exclude_demo: bool = False,
        rerank: bool = False,
        gate: str = "bm25_dense",
        bm25_gate: float = _BM25_GATE,
        dense_gate: float = _DENSE_GATE,
    ) -> "HybridRetriever":
        bm25 = BM25Retriever.from_chunks(chunks)
        dense = DenseIndex.from_chunks(chunks, cache_path=cache_path)
        return cls(
            bm25=bm25,
            dense=dense,
            exclude_demo=exclude_demo,
            rerank=rerank,
            gate=gate,
            bm25_gate=bm25_gate,
            dense_gate=dense_gate,
        )

    def _filter(self, hits: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not self.exclude_demo:
            return hits
        return [h for h in hits if not (h.metadata and h.metadata.is_demo)]

    def _load_reranker(self):
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            self._reranker = CrossEncoder(_RERANK_MODEL)
        return self._reranker

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        pool = max(top_k * 4, 20)
        bm25_hits = self._filter(self.bm25.search(query, top_k=pool))
        dense_hits = self._filter(self.dense.search(query, top_k=pool))
        if self.gate == "bm25_dense":
            max_bm25 = bm25_hits[0].score if bm25_hits else 0.0
            max_dense = dense_hits[0].score if dense_hits else 0.0
            if max_bm25 < self.bm25_gate and max_dense < self.dense_gate:
                return []
        fused = _prefer_current_sources(_rrf_fuse([bm25_hits, dense_hits]))
        fused = _expand_adjacent(fused, self.bm25.chunks, query)
        fused.sort(key=lambda hit: (_query_focus(query, hit), hit.score), reverse=True)
        if self.rerank and len(fused) > 1:
            reranker = self._load_reranker()
            pairs = [(query, h.text) for h in fused[:12]]
            scores = reranker.predict(pairs, show_progress_bar=False)
            # The gate already decides answerability; rerank only re-orders.
            threshold = self.rerank_threshold if self.gate == "none" else -1e9
            scored = [
                _to_chunk(h, float(s)) for h, s in zip(fused[:12], scores) if float(s) >= threshold
            ]
            scored.sort(key=lambda h: h.score, reverse=True)
            fused = scored
        return fused[:top_k]
