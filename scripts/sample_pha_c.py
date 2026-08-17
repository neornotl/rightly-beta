import json
import random
import re
import unicodedata

random.seed(20260814)

qs = [json.loads(l) for l in open("data/eval/gen_10k_realistic.jsonl", encoding="utf-8")]
rows = [json.loads(l) for l in open("results/eval_10k_text.jsonl", encoding="utf-8")]
byid = {r["question_id"]: r for r in rows}
chunks = {}
for l in open("data/chunks/real_chunks.jsonl", encoding="utf-8"):
    c = json.loads(l)
    chunks[c["chunk_id"]] = c.get("text", "")


def norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return set(re.findall(r"[a-z0-9_]{3,}", t))


STOP = {"bao", "hiem", "co", "va", "hoi", "cua", "cho", "toi", "con", "chao", "anh",
        "chi", "em", "duoc", "khong", "phai", "nen", "dang", "theo", "thu", "tuc",
        "nhu", "the", "nao", "gi", "ve", "vay", "lam", "sao", "moi", "ma", "la",
        "giup", "da", "dang"}

miss = []
for q in qs:
    if not q.get("expected_source_ids"):
        continue
    r = byid[q["question_id"]]
    if r["recall_at_5"] == 1:
        continue
    g = q.get("source_chunk_id") or (q["expected_source_ids"][0] + "::c1")
    gc = chunks.get(g, "")
    qw = norm(q["question_text"]) - STOP
    gw = norm(gc) - STOP
    miss.append({"qid": q["question_id"], "ov": len(qw & gw), "nq": len(qw),
                 "qt": q["question_text"], "gold": g, "gt": gc[:150]})

miss.sort(key=lambda m: m["ov"])
strat = miss[:40] + random.sample(miss[40:], 60)  # 40 overlap<=x + 60 random
with open("results/pha_c_sample100.jsonl", "w", encoding="utf-8") as f:
    for m in strat:
        f.write(json.dumps(m, ensure_ascii=False) + "\n")
print("written pha_c_sample100.jsonl (", len(strat), ")")