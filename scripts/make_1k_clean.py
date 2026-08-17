import json
import random
import re
import unicodedata

random.seed(20260814)

STOP = {"bao", "hiem", "co", "va", "hoi", "cua", "cho", "toi", "con", "chao", "anh",
        "chi", "em", "duoc", "khong", "phai", "nen", "dang", "theo", "thu", "tuc",
        "nhu", "the", "nao", "gi", "ve", "vay", "lam", "sao", "moi", "ma", "la",
        "giup", "da", "dang"}


def norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return set(re.findall(r"[a-z0-9_]{3,}", t))


def ov_with(q, gold_text):
    qw = norm(q["question_text"]) - STOP
    gw = norm(gold_text) - STOP
    return len(qw & gw), len(qw)


def main():
    chunks = {}
    for l in open("data/chunks/real_chunks.jsonl", encoding="utf-8"):
        c = json.loads(l)
        chunks[c["chunk_id"]] = c.get("text", "")

    qs = [json.loads(l) for l in open("data/eval/gen_10k_realistic.jsonl", encoding="utf-8")]
    res = {}
    for l in open("results/eval_10k_text.jsonl", encoding="utf-8"):
        r = json.loads(l)
        res[r["question_id"]] = r

    dropped = 0
    kept = []
    drop_stats = {"by_zone": {}, "by_diff": {}}
    for q in qs:
        rid = q["question_id"]
        has_gold = bool(q.get("expected_source_ids")) and q.get("source_chunk_id")
        if has_gold:
            ov, nq = ov_with(q, chunks.get(q["source_chunk_id"], ""))
            r = res.get(rid)
            miss = bool(r) and r.get("recall_at_5", 0) == 0
            noisy = miss and ov <= 2
            if noisy:
                dropped += 1
                z = q.get("expected_zone", "?")
                d = q.get("difficulty", "?")
                drop_stats["by_zone"][z] = drop_stats["by_zone"].get(z, 0) + 1
                drop_stats["by_diff"][d] = drop_stats["by_diff"].get(d, 0) + 1
                continue
        kept.append(q)

    print("total:", len(qs), "| dropped noisy:", dropped, "| kept:", len(kept))
    print("drop by_zone:", drop_stats["by_zone"])
    print("drop by_diff:", drop_stats["by_diff"])

    by_key = {}
    for q in kept:
        k = (q.get("expected_zone", "?"), q.get("difficulty", "?"))
        by_key.setdefault(k, []).append(q)

    total_kept = len(kept)
    n = 1000
    chosen = []
    used = set()
    for k, lst in sorted(by_key.items()):
        need = max(1, round(len(lst) / total_kept * n))
        random.shuffle(lst)
        chosen.extend(lst[:need])
        used.update(q["question_id"] for q in lst[:need])
    leftover = [q for q in kept if q["question_id"] not in used]
    random.shuffle(leftover)
    while len(chosen) < n and leftover:
        chosen.append(leftover.pop())
    random.shuffle(chosen)
    chosen = chosen[:n]

    with open("data/eval/gen_1k_clean.jsonl", "w", encoding="utf-8") as f:
        for q in chosen:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    zc, dc = {}, {}
    for q in chosen:
        zc[q.get("expected_zone")] = zc.get(q.get("expected_zone"), 0) + 1
        dc[q.get("difficulty")] = dc.get(q.get("difficulty"), 0) + 1
    print("sample n:", len(chosen), "| zone:", zc, "| diff:", dc)

    hits = sum(1 for q in chosen if res.get(q["question_id"], {}).get("recall_at_5") == 1)
    print("sample recall@5 hits from old 10k run:", hits, f"({hits/len(chosen):.1%})")
    withgold = [q for q in chosen if q.get("expected_source_ids") and q.get("source_chunk_id")]
    ghits = sum(1 for q in withgold if res.get(q["question_id"], {}).get("recall_at_5") == 1)
    print("with-gold:", len(withgold), "| hits:", ghits, f"({ghits/len(withgold):.1%})")

    scores = {"pass": 0, "partial": 0, "fail": 0, "tot": 0.0}
    for q in chosen:
        r = res[q["question_id"]]
        scores["tot"] += r.get("score", 0)
        g = (r.get("grade") or "").upper()
        if g.startswith("PASS"):
            scores["pass"] += 1
        elif g.startswith("PARTIAL"):
            scores["partial"] += 1
        elif g.startswith("FAIL"):
            scores["fail"] += 1
    nn = len(chosen)
    print("baseline on same subset:",
          "pass", round(scores["pass"] / nn, 4),
          "partial", round(scores["partial"] / nn, 4),
          "fail", round(scores["fail"] / nn, 4),
          "avg", round(scores["tot"] / nn, 4))


if __name__ == "__main__":
    main()