"""Pure-Python Okapi BM25 retriever (no numpy/scikit-learn needed)."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from app.retrieval.base import Retriever
from app.retrieval.document_loader import ChunkRecord, DocumentLoader
from app.schemas import RetrievedChunk

_TOKEN_RE = re.compile(
    r"[a-zA-Z0-9_]+|[àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]+",
    re.IGNORECASE,
)

_WORD_RE = re.compile(
    r"[a-zA-Z0-9_àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]+",
    re.IGNORECASE,
)

# Common Vietnamese function words excluded from matching so that generic
# queries ("là gì", "tôi muốn") cannot push scores above the threshold.
# NOTE: tokens are diacritic-stripped, so entries must be plain ASCII.
_VIETNAMESE_STOPWORDS = {
    "toi",
    "ban",
    "ong",
    "ba",
    "chu",
    "co",
    "chau",
    "em",
    "anh",
    "chi",
    "cua",
    "va",
    "voi",
    "la",
    "thi",
    "ma",
    "de",
    "cho",
    "tai",
    "o",
    "co",
    "khong",
    "phai",
    "nen",
    "se",
    "da",
    "dang",
    "duoc",
    "bi",
    "nay",
    "kia",
    "day",
    "gi",
    "nao",
    "sao",
    "vi",
    "nhung",
    "hay",
    "hoac",
    "neu",
    "cung",
    "rat",
    "nhung",
    "cac",
    "mot",
    "can",
    "muon",
    "hoi",
    "giup",
    "khi",
    "vao",
    "ra",
    "len",
    "xuong",
    "di",
    "lai",
    "xem",
    "toi",
    "con",
    "deu",
    "moi",
    "moi",
    "nguoi",
    "the",
    "lam",
}


def normalize_vietnamese(text: str) -> str:
    """Lowercase + strip diacritics (for matching robustness).

    ``đ``/``Đ`` is mapped to ``d`` *before* NFD decomposition so that a tone
    mark never splits ``điều`` into the junk tokens ``đ`` + ``ieu``.
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold()


@dataclass
class BM25Retriever(Retriever):
    """Okapi BM25 with default k1=1.5, b=0.75.

    ``min_token_overlap``: a document must share at least this many distinct
    query tokens (2 by default) to be returned. This is the primary guard
    against noise matches — a single generic word ("thế", "gì") must never
    look like a confident retrieval.
    """

    name: str = "bm25"
    k1: float = 1.5
    b: float = 0.75
    min_token_overlap: int = 2
    phrase_boost: float = 1.0
    phrase_boost_per_token: float = 0.4
    chunks: list[ChunkRecord] = field(default_factory=list)
    _doc_freqs: Counter = field(default_factory=Counter, repr=False)
    _doc_lens: list[int] = field(default_factory=list, repr=False)
    _avg_len: float = 0.0
    _doc_token_sets: list[set[str]] = field(default_factory=list, repr=False)
    _doc_tokens: list[list[str]] = field(default_factory=list, repr=False)
    _doc_words: list[list[str]] = field(default_factory=list, repr=False)
    _postings: dict[str, list[tuple[int, int]]] = field(default_factory=dict, repr=False)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens = [t.casefold() for t in _TOKEN_RE.findall(normalize_vietnamese(text))]
        return [t for t in tokens if t not in _VIETNAMESE_STOPWORDS]

    def _build(self) -> None:
        self._doc_lens = []
        self._doc_token_sets = []
        self._doc_tokens = []
        self._doc_words = []
        postings: dict[str, list[tuple[int, int]]] = {}
        all_freqs: Counter = Counter()
        for idx, chunk in enumerate(self.chunks):
            toks = self._tokenize(chunk.text)
            self._doc_lens.append(len(toks))
            uniq = set(toks)
            self._doc_token_sets.append(uniq)
            self._doc_tokens.append(toks)
            self._doc_words.append([w.casefold() for w in _WORD_RE.findall(chunk.text)])
            for t in uniq:
                all_freqs[t] += 1
            tf_counts: Counter = Counter(toks)
            for t, tf in tf_counts.items():
                postings.setdefault(t, []).append((idx, tf))
        self._doc_freqs = all_freqs
        self._postings = postings
        n = len(self.chunks)
        self._avg_len = (sum(self._doc_lens) / n) if n else 0.0

    @classmethod
    def from_jsonl(cls, chunks_path) -> "BM25Retriever":
        records = DocumentLoader.load_chunks(chunks_path)
        retriever = cls(chunks=records)
        retriever._build()
        return retriever

    @classmethod
    def from_chunks(cls, chunks: list[ChunkRecord]) -> "BM25Retriever":
        retriever = cls(chunks=chunks)
        retriever._build()
        return retriever

    def _score_doc(self, query_tokens: list[str], idx: int) -> float:
        if not query_tokens or not self.chunks:
            return 0.0
        n = len(self.chunks)
        uniq_q = set(query_tokens)
        doc_tokens = self._doc_token_sets[idx]
        doc_len = self._doc_lens[idx]
        score = 0.0
        for term in sorted(uniq_q):
            df = self._doc_freqs.get(term, 0)
            if df == 0 or term not in doc_tokens:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            tf = self._tokenize(self.chunks[idx].text).count(term)
            denom = tf + self.k1 * (1 - self.b + self.b * doc_len / self._avg_len)
            score += idf * (tf * (self.k1 + 1)) / denom
        return score

    def _score_doc_fast(self, query_tokens: list[str], pool: int = 2000) -> list[tuple[float, int]]:
        """Inverted-index BM25 scoring: only docs containing query terms.

        Returns the top-``pool`` scored docs (not all 16k) so search stays
        fast; overlap filtering happens in ``search`` afterwards.
        """
        if not query_tokens or not self.chunks:
            return []
        n = len(self.chunks)
        acc: dict[int, float] = {}
        for term in set(query_tokens):
            df = self._doc_freqs.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for idx, tf in self._postings.get(term, ()):
                doc_len = self._doc_lens[idx]
                denom = tf + self.k1 * (1 - self.b + self.b * doc_len / self._avg_len)
                acc[idx] = acc.get(idx, 0.0) + idf * (tf * (self.k1 + 1)) / denom
        if not acc:
            return []
        if len(acc) <= pool:
            return sorted(((s, i) for i, s in acc.items()), reverse=True)
        import heapq

        return heapq.nlargest(pool, ((s, i) for i, s in acc.items()))

    @staticmethod
    def _extract_phrases(words: list[str], max_len: int = 5) -> list[tuple[str, ...]]:
        """All contiguous word n-grams (2..max_len) from the query.

        Work on the *diacritic* word stream (never diacritic-stripped): plain
        "chương trình" must not fuse with "chứng", and "di chúc" must stay a
        phrase even though "di" looks like a stopword.
        """
        phrases: list[tuple[str, ...]] = []
        for width in range(2, max_len + 1):
            for i in range(len(words) - width + 1):
                span = words[i : i + width]
                if all(len(w) >= 2 for w in span):
                    phrases.append(tuple(span))
        return phrases

    def _phrase_score(self, phrases: list[tuple[str, ...]], idx: int) -> float:
        """Contiguous phrase hits in the doc, weighted by phrase length.

        Position maps make the scan O(sum over phrase words of positions),
        not O(doc_len x n_phrases).
        """
        toks = self._doc_words[idx]
        pos: dict[str, set[int]] = {}
        for i, w in enumerate(toks):
            pos.setdefault(w, set()).add(i)
        total = 0.0
        for ph in phrases:
            first = pos.get(ph[0])
            if first is None:
                continue
            hits = first
            shift = 1
            for w in ph[1:]:
                wpos = pos.get(w)
                if wpos is None:
                    hits = set()
                    break
                hits &= {p - shift for p in wpos}
                shift += 1
            count = len(hits)
            if count == 0:
                continue
            width = len(ph)
            base = self.phrase_boost + self.phrase_boost_per_token * (width - 2)
            total += base * min(count, 3)
        return total

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        if not self.chunks:
            return []
        query_tokens = self._tokenize(query)
        uniq_query = set(query_tokens)
        if not query_tokens:
            return []
        if len(uniq_query) == 1:
            # Council T3: single-token queries keep the overlap guard lifted,
            # but tokens that appear in >50% of the corpus are too generic to
            # match anything ("phường", "hồ sơ") — treat them as empty.
            token = next(iter(uniq_query))
            if self._doc_freqs.get(token, 0) > len(self.chunks) / 2:
                return []
        scored = self._score_doc_fast(query_tokens)
        phrases = self._extract_phrases([w.casefold() for w in _WORD_RE.findall(query)])
        if phrases:
            boosted: list[tuple[float, int]] = []
            for score, idx in scored:
                boosted.append((score + self._phrase_score(phrases, idx), idx))
            boosted.sort(reverse=True)
            scored = boosted
        results: list[RetrievedChunk] = []
        for score, idx in scored:
            if score <= 0.0:
                break
            overlap = len(uniq_query & self._doc_token_sets[idx])
            if overlap < self.min_token_overlap and len(uniq_query) > 1:
                continue
            rec = self.chunks[idx]
            results.append(
                RetrievedChunk(
                    chunk_id=rec.chunk_id,
                    source_id=rec.source_id,
                    text=rec.text,
                    score=round(score, 4),
                    metadata=DocumentLoader.to_metadata(rec),
                )
            )
            if len(results) >= top_k:
                break
        return results
