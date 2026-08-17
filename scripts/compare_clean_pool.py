import json

qs = [json.loads(l) for l in open("data/eval/gen_10k_realistic.jsonl", encoding="utf-8")]
res = {}
for l in open("results/eval_10k_text.jsonl", encoding="utf-8"):
    r = json.loads(l)
    res[r["question_id"]] = r
keep_ids = set()
for l in open("data/eval/gen_1k_clean.jsonl", encoding="utf-8"):
    keep_ids.add(json.loads(l)["question_id"])
# reconstruct dropped = 10k minus all kept (kept pool = 9086)
kept = [q for q in qs if q["question_id"] in keep_ids]
# to get full kept pool (9086), infer from the 1k file's parent: we don't have it saved -> recompute dropping rule quickly
import re
import unicodedata
STOP = {"bao", "hiem", "co", "va", "hoi", "cua", "cho", "toi", "con", "chao", "anh",
        "chi", "em", "duoc", "khong", "phai", "nen", "dang", "theo", "thu", "tuc",
        "nhu", "the", "nao", "gi", "ve", "vay", "lam", "sao", "moi", "ma", "la",
        "giup", "da", "dang"}
chunks = {}
for l in open("data/chunks/real_chunks.jsonl", encoding="utf-8"):
    c = json.loads(l)
    chunks[c["chunk_id"]] = c.get("text", "")


def norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return set(re.findall(r"[a-z0-9_]{3,}", t))


def ov_with(q, gold_text):
    return len((norm(q["question_text"]) - STOP) & (norm(gold_text) - STOP))


def is_noisy(q):
    if not (q.get("expected_source_ids") and q.get("source_chunk_id")):
        return False
    r = res.get(q["question_id"], {})
    if r.get("recall_at_5"):
        return False
    return ov_with(q, chunks.get(q["source_chunk_id"], "")) <= 2


dropped = [q for q in qs if is_noisy(q)]
kept_pool = [q for q in qs if not is_noisy(q)]
print("dropped:", len(dropped), "| kept pool:", len(kept_pool))


def agg(lst, label):
    n = len(lst)
    if not n:
        return
    p = pa = f = 0
    tot = 0.0
    for q in lst:
        r = res[q["question_id"]]
        tot += r.get("score", 0)
        g = (r.get("grade") or "").upper()
        if g.startswith("PASS"):
            p += 1
        elif g.startswith("PARTIAL"):
            pa += 1
        elif g.startswith("FAIL"):
            f += 1
    print(label, "n=", n, "| pass", round(p / n, 4), "| partial", round(pa / n, 4),
          "| fail", round(f / n, 4), "| avg", round(tot / n, 4))


agg(qs, "full 10k (old run):")
agg(kept_pool, "kept pool 9086 (old run):")
agg(dropped, "dropped 914 noisy (old run):")