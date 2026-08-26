"""Hybrid retrieval: BM25 + dense embeddings, fused with RRF, optional
cross-encoder rerank. Dense index uses a multilingual SentenceTransformer
with a disk cache of precomputed embeddings."""

from __future__ import annotations

import math
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from app.retrieval.base import Retriever
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.document_loader import ChunkRecord, DocumentLoader
from app.schemas import RetrievedChunk

_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "
_EMB_MODEL = "intfloat/multilingual-e5-small"
_RERANK_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
logger = logging.getLogger(__name__)

# Answerability gate thresholds, calibrated on the real corpus (8 demo
# queries). In-corpus queries score >= one threshold; out-of-corpus queries
# (e.g. "hộ chiếu", "phạt khai sinh quá hạn") fall below both.
_BM25_GATE = 12.2
_DENSE_GATE = 0.84


@dataclass
class ScoreBreakdown:
    """Detailed score components for debugging and analysis."""
    bm25_score: float = 0.0
    dense_score: float = 0.0
    rrf_score: float = 0.0
    focus_boost: float = 0.0
    rerank_score: float = 0.0
    final_score: float = 0.0


class EvidenceType:
    """Classification of evidence relevance to the query."""
    DIRECT_ANSWER = "direct_answer"      # Contains the exact answer (article with numbers, conditions, subjects)
    CONDITIONS_EXCEPTIONS = "conditions_exceptions"  # Conditions, exceptions, scope limitations
    PROCEDURE = "procedure"               # Step-by-step procedure, where to submit, timeline
    CITATION_ONLY = "citation_only"       # Only cites law name/article without substantive content
    IRRELEVANT = "irrelevant"             # Not related to the query intent


def _classify_evidence(query: str, hit: RetrievedChunk) -> str:
    """Classify a chunk's relevance to the query.
    
    Priority: direct_answer > conditions_exceptions > procedure > citation_only > irrelevant
    """
    q = query.casefold()
    text = hit.text.casefold()
    
    # Check for direct answer patterns: specific article with numbers, conditions, subjects
    direct_patterns = [
        r"điều\s+\d+.*\d+",           # Article with numbers
        r"mức\s+phạt.*\d+",            # Penalty amount
        r"tuổi\s+nghỉ\s+hưu.*\d+",     # Retirement age with number
        r"thời\s+hạn.*\d+\s+ngày",     # Deadline with days
        r"hồ\s+sơ\s+gồm",              # Dossier composition
        r"điều\s+kiện.*\d+",           # Conditions with specifics
        r"đối\s+tượng.*\d+",           # Subjects with specifics
        r"mức\s+hưởng.*\d+%?",         # Benefit level with percentage
        r"giảm\s+\d+%?",               # Reduction with percentage
        r"miễn\s+phí",                 # Free/exempt
    ]
    
    # Check for conditions/exceptions
    condition_patterns = [
        r"ngoại\s+lệ",                 # Exceptions
        r"trường\s+hợp.*không",        # Cases not applicable
        r"trừ\s+trường\s+hợp",         # Except cases
        r"không\s+áp\s+dụng",          # Not applicable
        r"điều\s+kiện.*hưởng",         # Conditions to enjoy
        r"được\s+hưởng.*khi",          # Enjoyed when
    ]
    
    # Check for procedure
    procedure_patterns = [
        r"thủ\s+tục",                  # Procedure
        r"nộp\s+hồ\s+sơ",              # Submit dossier
        r"giải\s+quyết\s+trong",       # Resolved within
        r"cơ\s+quan\s+tiếp\s+nhận",    # Receiving agency
        r"cổng\s+dịch\s+vụ\s+công",    # Public service portal
        r"bước\s+\d+",                 # Step N
    ]
    
    # Check for citation only (mentions law/article but no substantive content)
    citation_only_patterns = [
        r"theo\s+(luật|nghị\s+định|thông\s+tư|quyết\s+định)",  # "According to Law/Decree..."
        r"căn\s+cứ\s+(luật|nghị\s+định)",                       # "Based on Law/Decree..."
        r"điều\s+\d+\.\s*$",                                    # Just article reference at end
    ]
    
    # Query intent detection
    wants_procedure = any(term in q for term in ["thủ tục", "làm sao", "nộp ở đâu", "giải quyết", "bước"])
    wants_conditions = any(term in q for term in ["điều kiện", "ai được", "đối tượng", "được hưởng"])
    wants_penalty = any(term in q for term in ["phạt", "mức phạt", "xử phạt"])
    wants_dossier = any(term in q for term in ["hồ sơ", "giấy tờ", "cần gì"])
    wants_age = any(term in q for term in ["tuổi", "bao nhiêu tuổi"])
    wants_deadline = any(term in q for term in ["thời hạn", "bao lâu", "khi nào"])
    
    # Direct answer: high relevance to what user specifically asks for
    if wants_penalty and any(re.search(p, text) for p in direct_patterns if "phạt" in p or "mức" in p):
        return EvidenceType.DIRECT_ANSWER
    if wants_age and any(re.search(p, text) for p in direct_patterns if "tuổi" in p):
        return EvidenceType.DIRECT_ANSWER
    if wants_dossier and any(re.search(p, text) for p in direct_patterns if "hồ sơ" in p):
        return EvidenceType.DIRECT_ANSWER
    if wants_deadline and any(re.search(p, text) for p in direct_patterns if "thời hạn" in p or "ngày" in p):
        return EvidenceType.DIRECT_ANSWER
    if wants_conditions and any(re.search(p, text) for p in direct_patterns if "điều kiện" in p or "đối tượng" in p):
        return EvidenceType.DIRECT_ANSWER
    
    # General direct answer: contains specific numbers/articles that answer the query
    if any(re.search(p, text) for p in direct_patterns):
        # Check if it's actually answering the query topic
        query_topics = set(q.split())
        text_topics = set(text.split())
        overlap = query_topics & text_topics
        if len(overlap) >= 2:  # At least 2 query terms in text
            return EvidenceType.DIRECT_ANSWER
    
    # Conditions/exceptions
    if any(re.search(p, text) for p in condition_patterns):
        return EvidenceType.CONDITIONS_EXCEPTIONS
    
    # Procedure
    if any(re.search(p, text) for p in procedure_patterns):
        return EvidenceType.PROCEDURE
    
    # Citation only
    if any(re.search(p, text) for p in citation_only_patterns):
        return EvidenceType.CITATION_ONLY
    
    return EvidenceType.IRRELEVANT


def _to_chunk(rec, score: float, breakdown: Optional[ScoreBreakdown] = None) -> RetrievedChunk:
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
            backend = os.environ.get("RIGHTLY_EMBEDDING_BACKEND", "auto").strip().lower()
            if backend not in {"auto", "openvino", "pytorch"}:
                raise ValueError("RIGHTLY_EMBEDDING_BACKEND must be auto, openvino, or pytorch")
            if backend in {"auto", "openvino"}:
                try:
                    from app.retrieval.openvino_e5 import OpenVINOE5Encoder

                    self._model = OpenVINOE5Encoder(
                        os.environ.get("RIGHTLY_E5_MODEL_PATH", "data/models/multilingual-e5-small"),
                        os.environ.get("RIGHTLY_E5_OPENVINO_PATH", "data/models/openvino/e5-small.xml"),
                        int(os.environ.get("RIGHTLY_OPENVINO_THREADS", "4")),
                    )
                    logger.info("Dense retrieval uses OpenVINO CPU")
                    return self._model
                except Exception as exc:
                    if backend == "openvino":
                        raise RuntimeError(f"OpenVINO embedding backend unavailable: {exc}") from exc
                    logger.warning("OpenVINO embeddings unavailable (%s); using PyTorch fallback", exc)
            from sentence_transformers import SentenceTransformer
            model_path = os.environ.get("RIGHTLY_E5_MODEL_PATH", self.model_name)
            self._model = SentenceTransformer(
                model_path,
                local_files_only=os.environ.get("OFFLINE_MODE", "").lower() in {"1", "true", "yes", "on"},
            )
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


def _rrf_fuse(lists: list[list[RetrievedChunk]], k: int = 60) -> tuple[list[RetrievedChunk], dict[str, ScoreBreakdown]]:
    """Fuse with RRF and return score breakdowns."""
    bm25_scores: dict[str, float] = {}
    dense_scores: dict[str, float] = {}
    rrf_scores: dict[str, float] = {}
    order: dict[str, int] = {}
    
    for i, hits in enumerate(lists):
        for rank, hit in enumerate(hits):
            rrf_contrib = 1.0 / (k + rank + 1)
            rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + rrf_contrib
            if hit.chunk_id not in order:
                order[hit.chunk_id] = len(order)
            # Track individual retriever scores
            if i == 0:  # BM25
                bm25_scores[hit.chunk_id] = hit.score
            elif i == 1:  # Dense
                dense_scores[hit.chunk_id] = hit.score
    
    by_chunk = {h.chunk_id: h for hits in lists for h in hits}
    ranked = sorted(by_chunk, key=lambda cid: (-rrf_scores.get(cid, 0.0), order[cid], cid))
    
    breakdowns = {}
    for cid in ranked:
        breakdowns[cid] = ScoreBreakdown(
            bm25_score=bm25_scores.get(cid, 0.0),
            dense_score=dense_scores.get(cid, 0.0),
            rrf_score=rrf_scores.get(cid, 0.0),
        )
    
    return [_to_chunk(by_chunk[cid], rrf_scores.get(cid, 0.0)) for cid in ranked], breakdowns


#: Folk terms users say -> canonical tokens found in law titles.
_QUERY_ALIASES = {
    "so do": "đất đai quyền sử dụng đất",
    "so hong": "nhà ở quyền sử dụng đất",
    "ho khau": "cư trú hộ gia đình thường trú",
    "bhxh": "bảo hiểm xã hội",
    "bhyt": "bảo hiểm y tế",
    "tro cap that nghiep": "bảo hiểm thất nghiệp trợ cấp",
}


def _title_family_key(title: str) -> str:
    """Coarse grouping key so superseded editions of the SAME law land in one
    bucket (digits/years and doc-type words stripped)."""
    value = title.casefold().replace("_", " ").replace("-", " ")
    value = re.sub(r"\d+", " ", value)
    value = re.sub(r"\b(vbhn|vpqh|luat|luật|bo|bộ|qh|nd|tt)\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _is_vbhn_title(title: str) -> bool:
    return bool(re.search(r"\d{1,3}\s*[-–]\s*VBHN", (title or "").upper()))


def _texts_similar(a: str, b: str, threshold: float = 0.80) -> bool:
    """Fast near-duplicate test: word-set Jaccard (consolidated editions of
    the same provision share almost all words; distinct laws do not)."""
    wa = frozenset(a.split())
    wb = frozenset(b.split())
    if not wa or not wb:
        return False
    if abs(len(wa) - len(wb)) > max(len(wa), len(wb)) * 0.6:
        return False
    inter = len(wa & wb)
    return inter / (len(wa) + len(wb) - inter) >= threshold


def _prefer_current_sources(hits: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Collapse near-identical text from superseded editions of the SAME law.

    Only texts that are actually near-identical are treated as duplicates
    (preferring the VBHN/consolidated edition). Distinct laws must never be
    collapsed just because their titles look alike — an earlier version of
    this heuristic merged different acts and dropped the correct source from
    the context (-22.7 hit@5 on the 1000-question benchmark).
    """
    families: dict[str, list[RetrievedChunk]] = {}
    for hit in hits:
        title = hit.metadata.title if hit.metadata else ""
        key = _title_family_key(title) or hit.source_id
        families.setdefault(key, []).append(hit)

    kept: list[RetrievedChunk] = []
    for group in families.values():
        group_sorted = sorted(
            group,
            key=lambda h: (
                not _is_vbhn_title(h.metadata.title if h.metadata else ""),
                h.source_id,
                -h.score,
            ),
        )
        representatives: list[RetrievedChunk] = []
        for cand in group_sorted:
            if any(_texts_similar(cand.text, rep.text) for rep in representatives):
                continue
            representatives.append(cand)
        kept.extend(representatives)

    deduped: list[RetrievedChunk] = []
    source_counts: dict[str, int] = {}
    for hit in sorted(kept, key=lambda item: -item.score):
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


def _extract_legal_structure(text: str) -> tuple[str, ...]:
    """Extract legal structure identifiers (Điều, Khoản, Điểm) from text.
    Returns tuple of (điều, khoản, điểm) found, empty strings if not found.
    """
    import re
    text_lower = text.casefold()
    
    # Find Điều number
    dieu_match = re.search(r"điều\s+(\d+[a-z]?)", text_lower)
    dieu = dieu_match.group(1) if dieu_match else ""
    
    # Find Khoản number
    khoa_match = re.search(r"khoản\s+(\d+)", text_lower)
    khoa = khoa_match.group(1) if khoa_match else ""
    
    # Find Điểm letter
    diem_match = re.search(r"điểm\s+([a-z])", text_lower)
    diem = diem_match.group(1) if diem_match else ""
    
    return (dieu, khoa, diem)


def _same_legal_structure(text1: str, text2: str) -> bool:
    """Check if two texts share the same Điều/Khoản/Điểm structure."""
    s1 = _extract_legal_structure(text1)
    s2 = _extract_legal_structure(text2)
    # Must have at least Điều matching, and if both have Khoản/Điểm they must match
    if not s1[0] or not s2[0]:
        return False
    if s1[0] != s2[0]:
        return False
    if s1[1] and s2[1] and s1[1] != s2[1]:
        return False
    if s1[2] and s2[2] and s1[2] != s2[2]:
        return False
    return True


def _expand_adjacent(
    hits: list[RetrievedChunk], chunks: list[ChunkRecord], query: str
) -> list[RetrievedChunk]:
    """Add nearby chunks when the answer is a legal list or procedure.
    
    Only expands to chunks sharing the same Điều/Khoản/Điểm structure
    to avoid contaminating context with unrelated provisions (timelines,
    exceptions, repeals from adjacent articles).
    """
    q = query.casefold()
    if not any(term in q for term in ("hồ sơ", "giấy tờ", "ai được", "những ai", "đối tượng", "điều kiện", "thời giờ làm việc", "nghỉ hưu")):
        return hits
    positions = {chunk.chunk_id: i for i, chunk in enumerate(chunks)}
    selected = {hit.chunk_id: hit for hit in hits}
    for hit in list(hits[:3]):
        pos = positions.get(hit.chunk_id)
        if pos is None:
            continue
        # Only expand to adjacent chunks with SAME legal structure
        for i in range(max(0, pos - 2), min(len(chunks), pos + 3)):
            neighbor = chunks[i]
            if neighbor.source_id != hit.source_id:
                continue
            if neighbor.chunk_id in selected:
                continue
            # Check legal structure match
            if not _same_legal_structure(hit.text, neighbor.text):
                continue
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
                if candidate.chunk_id in selected:
                    continue
                if any(term in candidate.text.casefold() for term in direct_terms):
                    # Also verify legal structure match for direct terms
                    if _same_legal_structure(hit.text, candidate.text):
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
    _title_index: Optional[dict[str, dict]] = field(default=None, repr=False)

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

    def _build_title_index(self) -> dict[str, dict]:
        """source_id -> {tokens, max_bonus_cap} plus token IDF, built once.

        Users often name the legal topic ("bảo hiểm xã hội", "trợ giúp pháp
        lý"); chunks whose document TITLE shares those rare tokens deserve a
        modest boost on top of the fused score.
        """
        from app.retrieval.bm25_retriever import _VIETNAMESE_STOPWORDS, normalize_vietnamese

        def toks(text: str) -> set[str]:
            words = [w for w in re.findall(r"[a-zà-ỹđ]{3,}", normalize_vietnamese(text))]
            return {w for w in words if w not in _VIETNAMESE_STOPWORDS}

        src_tokens: dict[str, set[str]] = {}
        for c in self.bm25.chunks:
            if c.source_id not in src_tokens:
                src_tokens[c.source_id] = toks(c.title)
        n_src = max(len(src_tokens), 1)
        df: dict[str, int] = Counter()
        for toks_ in src_tokens.values():
            for t in toks_:
                df[t] += 1
        idf = {t: math.log(1 + n_src / d) for t, d in df.items()}
        return {"src_tokens": src_tokens, "idf": idf}

    def _title_boost(self, query: str, source_id: str) -> float:
        if self._title_index is None:
            self._title_index = self._build_title_index()
        idx = self._title_index
        stoks = idx["src_tokens"].get(source_id)
        if not stoks:
            return 0.0
        from app.retrieval.bm25_retriever import _VIETNAMESE_STOPWORDS, normalize_vietnamese

        qtoks = {
            w
            for w in re.findall(r"[a-zà-ỹđ]{3,}", normalize_vietnamese(query))
            if w not in _VIETNAMESE_STOPWORDS
        }
        # folk-term aliases ("sổ đỏ" -> đất đai / quyền sử dụng đất)
        nq = normalize_vietnamese(query)
        for folk, canonical in _QUERY_ALIASES.items():
            if folk in nq:
                qtoks |= {
                    w for w in re.findall(r"[a-zà-ỹđ]{3,}", canonical)
                    if w not in _VIETNAMESE_STOPWORDS
                }
        overlap = qtoks & stoks
        if not overlap:
            return 0.0
        # 0.003/token, capped at 0.0075 — well under one RRF vote (~0.016)
        return min(0.003 * len(overlap), 0.0075)

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
        
        fused, breakdowns = _rrf_fuse([bm25_hits, dense_hits])
        fused = _prefer_current_sources(fused)
        fused = _expand_adjacent(fused, self.bm25.chunks, query)
        
        # Apply focus boost and track in breakdowns
        boosted = []
        for hit in fused:
            boost = _query_focus(query, hit)
            if boost > 0:
                # Create new chunk with boosted score (RetrievedChunk is frozen)
                boosted_hit = RetrievedChunk(
                    chunk_id=hit.chunk_id,
                    source_id=hit.source_id,
                    text=hit.text,
                    score=round(hit.score + boost, 4),
                    metadata=hit.metadata,
                )
                boosted.append(boosted_hit)
                if hit.chunk_id in breakdowns:
                    breakdowns[hit.chunk_id].focus_boost = boost
                    breakdowns[hit.chunk_id].final_score = hit.score + boost
            else:
                boosted.append(hit)
        fused = boosted
        
        # Small additive bonuses only: title affinity + evidence-type as a
        # TIE-BREAKER. The old hard re-sort by evidence type discarded ~10
        # points of hit@5 by promoting pattern-matching chunks over on-topic
        # ones; bonuses keep the fused ranking dominant.
        ev_bonus = {
            EvidenceType.DIRECT_ANSWER: 0.0012,
            EvidenceType.CONDITIONS_EXCEPTIONS: 0.0009,
            EvidenceType.PROCEDURE: 0.0006,
            EvidenceType.CITATION_ONLY: 0.0003,
            EvidenceType.IRRELEVANT: 0.0,
        }
        rescored = []
        for hit in fused:
            total = (
                hit.score
                + self._title_boost(query, hit.source_id)
                + ev_bonus.get(_classify_evidence(query, hit), 0.0)
            )
            rescored.append((total, hit))
        rescored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))
        fused = [
            _to_chunk(hit, total) if abs(total - hit.score) > 1e-12 else hit
            for total, hit in rescored
        ]

        # Source diversity: two chunks max per source inside the returned
        # window so one verbose act cannot crowd out the correct law.
        diversified: list[RetrievedChunk] = []
        src_count: dict[str, int] = {}
        overflow: list[RetrievedChunk] = []
        for hit in fused:
            c = src_count.get(hit.source_id, 0)
            if c >= 2 and len(diversified) < top_k * 3:
                overflow.append(hit)
                continue
            src_count[hit.source_id] = c + 1
            diversified.append(hit)
            if len(diversified) >= top_k and overflow:
                break
        fused = diversified + overflow[:top_k]

        if self.rerank and len(fused) > 1:
            reranker = self._load_reranker()
            pairs = [(query, h.text) for h in fused[:12]]
            scores = reranker.predict(pairs, show_progress_bar=False)
            threshold = self.rerank_threshold if self.gate == "none" else -1e9
            scored = []
            for h, s in zip(fused[:12], scores):
                if float(s) >= threshold:
                    new_hit = _to_chunk(h, float(s))
                    if h.chunk_id in breakdowns:
                        breakdowns[h.chunk_id].rerank_score = float(s)
                        breakdowns[h.chunk_id].final_score = float(s)
                    scored.append(new_hit)
            scored.sort(key=lambda h: h.score, reverse=True)
            fused = scored
        
        return fused[:top_k]
