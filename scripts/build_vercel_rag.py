# -*- coding: utf-8 -*-
"""Build a compact BM25 retrieval pack for the Vercel serverless handler.

Serverless constraints (stdlib-only handler, ~20s budget, 250MB unzip):
  - full 34k-chunk corpus + embeddings cannot ride along usefully
  -> curate high-value domains for the elderly audience, cap total chunks,
     ship an inverted-index JSON.gz + texts JSON.gz under api/rag/.

Outputs:
  api/rag/index.json.gz   postings/doclens/meta (chunk_id|source_id|title)
  api/rag/texts.json.gz   chunk_id -> text
"""

from __future__ import annotations

import gzip
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "api" / "rag"

MAX_CHUNKS = 14000
CHUNK_CHARS_CAP = 900

# Domain priority: elderly public-service topics first.
DOMAIN_RULES = [
    (("bảo hiểm xã hội", "hưu", "trợ cấp thất nghiệp", "bhxh"), 0),
    (("bảo hiểm y tế", "bhyt", "khám chữa bệnh"), 0),
    (("cư trú", "thường trú", "tạm trú"), 0),
    (("hộ tịch", "khai sinh", "kết hôn", "ly hôn"), 0),
    (("trợ giúp pháp lý",), 0),
    (("người cao tuổi", "người khuyết tật", "bạo lực gia đình", "trẻ em"), 0),
    (("đất đai", "quyền sử dụng đất", "nhà ở"), 1),
    (("giao thông đường bộ", "giấy phép lái xe"), 1),
    (("lao động", "tiền lương tối thiểu", "hợp đồng lao động"), 1),
    (("xử phạt vi phạm hành chính", "vi phạm hành chính"), 1),
    (("thi hành án", "khiếu nại", "tố cáo"), 2),
    (("quốc tịch",), 2),
    (("di chúc", "thừa kế", "di sản"), 2),
    (("hình sự",), 3),
]

_STOP = {
    "toi", "ban", "ong", "ba", "chu", "co", "chau", "em", "anh", "chi", "cua",
    "va", "voi", "la", "thi", "ma", "de", "cho", "tai", "o", "khong", "phai",
    "nen", "se", "da", "dang", "duoc", "bi", "nay", "kia", "day", "gi", "nao",
    "sao", "vi", "nhung", "hay", "hoac", "neu", "cung", "rat", "cac", "mot",
    "can", "muon", "hoi", "giup", "khi", "vao", "ra", "len", "xuong", "di",
    "lai", "xem", "con", "deu", "moi", "nguoi", "the", "lam",
}


def norm_tokens(text: str) -> list[str]:
    t = text.replace("đ", "d").replace("Đ", "D")
    t = unicodedata.normalize("NFD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).casefold()
    toks = re.findall(r"[a-z0-9]+", t)
    return [t for t in toks if t not in _STOP]


def domain_rank(source_id: str, status_db: dict) -> int:
    info = status_db.get(source_id) or {}
    hay = f"{info.get('trich_yeu', '')} {info.get('loai', '')}".casefold()
    best = 99
    for keys, rank in DOMAIN_RULES:
        if any(k in hay for k in keys):
            best = min(best, rank)
    return best


def main() -> None:
    records = [
        json.loads(line)
        for line in (ROOT / "data/chunks/real_chunks.jsonl").open(encoding="utf-8")
        if line.strip()
    ]
    status_db = json.loads((ROOT / "data/law_status.json").read_text(encoding="utf-8"))["sources"]

    # dedupe identical text (same provision across editions) keeping first
    seen_text: set[str] = set()
    pool = []
    for r in records:
        key = " ".join(r["text"].split())[:300]
        if key in seen_text:
            continue
        seen_text.add(key)
        if len(r["text"].strip()) < 60:
            continue
        pool.append(r)

    # prioritize by domain then newer year in source id
    def sort_key(r):
        sid = r["source_id"]
        yr = sid.rsplit("_", 1)[-1]
        year = int(yr) if yr.isdigit() else 0
        return (domain_rank(sid, status_db), -year)

    pool.sort(key=sort_key)
    selected = pool[:MAX_CHUNKS]
    print(f"selected {len(selected)} / {len(records)} chunks")

    doclens: list[int] = []
    postings: dict[str, list] = {}
    meta: list[dict] = []
    texts: dict[str, str] = {}

    for idx, r in enumerate(selected):
        text = r["text"][:CHUNK_CHARS_CAP]
        toks = norm_tokens(text)
        doclens.append(len(toks))
        meta.append({
            "cid": r["chunk_id"],
            "sid": r["source_id"],
            "ti": (r.get("title") or "")[:80],
        })
        texts[r["chunk_id"]] = text
        for term, tf in Counter(toks).items():
            postings.setdefault(term, []).append([idx, tf])

    avgdl = sum(doclens) / max(len(doclens), 1)
    index_payload = {
        "k1": 1.5,
        "b": 0.75,
        "avgdl": avgdl,
        "N": len(selected),
        "doclens": doclens,
        "meta": meta,
        # drop ultra-frequent terms to shrink payload
        "postings": {
            t: p for t, p in postings.items()
            if len(p) > 3 and len(t) >= 2 and len(p) < len(selected) * 0.5
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    idx_bytes = gzip.compress(json.dumps(index_payload, ensure_ascii=False).encode("utf-8"), 9)
    txt_bytes = gzip.compress(json.dumps(texts, ensure_ascii=False).encode("utf-8"), 9)
    (OUT_DIR / "index.json.gz").write_bytes(idx_bytes)
    (OUT_DIR / "texts.json.gz").write_bytes(txt_bytes)
    print(f"index.json.gz {len(idx_bytes)/1e6:.1f} MB | texts.json.gz {len(txt_bytes)/1e6:.1f} MB")
    print(f"terms={len(index_payload['postings'])} avgdl={avgdl:.0f}")


if __name__ == "__main__":
    main()
