import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import numpy as np
from sentence_transformers import SentenceTransformer

from app.retrieval.bm25_retriever import BM25Retriever, normalize_vietnamese
from app.retrieval.document_loader import DocumentLoader

_QUERY_PREFIX = "query: "
_BM25_GATE = 12.2
_DENSE_GATE = 0.84
_EXTRA_NOISE = {"bua", "nay", "gium", "dum", "gup", "du", "ac", "chau", "bac", "chu", "ua",
                "oi", "ne", "nghe", "lai", "day", "do", "dung", "dung", "xem"}


def normed_tokens(text):
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9_]+", t)


def load_chunk_texts():
    chunks = {}
    for l in open("data/chunks/real_chunks.jsonl", encoding="utf-8"):
        c = json.loads(l)
        chunks[c["chunk_id"]] = c.get("text", "")
    return chunks


def build_vocab(chunk_texts):
    vocab = set()
    first_char = defaultdict(list)
    diacritic_map = defaultdict(set)
    for t in chunk_texts.values():
        for raw in re.findall(r"[a-zA-Z0-9_]+", t):
            nrm = normalize_vietnamese(raw)
            if len(nrm) >= 3:
                vocab.add(nrm)
                first_char[nrm[0]].append(nrm)
                if raw != nrm:
                    diacritic_map[nrm].add(raw.casefold())
    return vocab, first_char, diacritic_map


def damerau_leven2(a, b, cap=2):
    if abs(len(a) - len(b)) > cap or (a and b and a[0] != b[0]):
        return cap + 1
    la, lb = len(a), len(b)
    if la < lb:
        a, b = b, a
        la, lb = lb, la
    if lb == 0:
        return la if la <= cap else cap + 1
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev[j - 2] + 1)
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[lb]


class Normalizer:
    def __init__(self, vocab, first_char, diacritic_map):
        self.vocab = vocab
        self.first_char = first_char
        self.diacritic_map = diacritic_map
        self._cache = {}
        self._fixed = defaultdict(list)

    def fix_typo(self, tok):
        if tok in self.vocab or tok in _EXTRA_NOISE or len(tok) < 4:
            return tok
        if tok in self._cache:
            return self._cache[tok]
        cands = [c for c in self.first_char.get(tok[0], []) if abs(len(c) - len(tok)) <= 2]
        best, bestd = tok, 2
        for c in cands:
            if c == tok:
                continue
            d = damerau_leven2(tok, c, cap=2)
            if d < bestd:
                best, bestd = c, d
        if bestd < 2 and best != tok:
            self._fixed[tok].append(best)
        self._cache[tok] = best if bestd < 2 else tok
        return self._cache[tok]

    def fix_text(self, text):
        toks = normed_tokens(text)
        fixed = []
        for t in toks:
            if t in _EXTRA_NOISE or t in self.vocab:
                fixed.append(t)
            else:
                fixed.append(self.fix_typo(t))
        return " ".join(fixed)

    def restore_diacritics(self, text):
        out = []
        for w in re.split(r"([^a-zA-Z0-9_]+)", text):
            if not w or not w[0].isalpha():
                out.append(w)
                continue
            nrm = normalize_vietnamese(w)
            cands = self.diacritic_map.get(nrm)
            if cands and len(cands) == 1:
                out.append(list(cands)[0])
            else:
                out.append(w)
        return "".join(out)


def main():
    chunks = load_chunk_texts()
    vocab, first_char, diac_map = build_vocab(chunks)
    nz = Normalizer(vocab, first_char, diac_map)

    questions = [json.loads(l) for l in open("data/eval/gen_1k_clean.jsonl", encoding="utf-8")]
    wg = [q for q in questions if q.get("expected_source_ids") and q.get("source_chunk_id")]
    print("n with-gold:", len(wg))
    nz_src = sum(1 for q in wg if len(q.get("expected_source_ids") or []) > 1)
    print("multi-source:", nz_src)

    chunk_recs = DocumentLoader.load_chunks("data/chunks/real_chunks.jsonl")
    bm = BM25Retriever.from_chunks(chunk_recs)
    model = SentenceTransformer("intfloat/multilingual-e5-small")

    emb = np.load("data/chunks/real_embeddings.npz", allow_pickle=True)
    emb_ids = list(emb["ids"])
    emb_arr = emb["embeddings"]
    id2idx = {cid: i for i, cid in enumerate(emb_ids)}

    def eval_variant(name, bm_q, dense_q):
        r1 = r3 = r5 = 0
        mrr = 0.0
        gated = 0
        for q in wg:
            expected = q.get("expected_source_ids") or []
            bm_hits = bm.search(bm_q(q["question_text"]), top_k=20)
            qv = model.encode([_QUERY_PREFIX + dense_q(q["question_text"])], normalize_embeddings=True)[0]
            sims = emb_arr @ qv
            order = np.argsort(-sims)[:20]
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
            ids = [cid for cid, _ in ranked][:5]
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
    eval_variant("baseline   ", lambda t: t, lambda t: t)
    print("  sec:", round(time.perf_counter() - t0, 1))
    t0 = time.perf_counter()
    eval_variant("typo+diac  ", nz.fix_text, nz.restore_diacritics)
    print("  sec:", round(time.perf_counter() - t0, 1))
    t0 = time.perf_counter()
    eval_variant("typo only  ", nz.fix_text, lambda t: t)
    print("  sec:", round(time.perf_counter() - t0, 1))
    t0 = time.perf_counter()
    eval_variant("diac only  ", lambda t: t, nz.restore_diacritics)
    print("  sec:", round(time.perf_counter() - t0, 1))


if __name__ == "__main__":
    main()