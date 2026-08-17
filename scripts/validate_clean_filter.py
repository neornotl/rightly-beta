import json
import re
import unicodedata

STOP = {"bao", "hiem", "co", "va", "hoi", "cua", "cho", "toi", "con", "chao", "anh",
        "chi", "em", "duoc", "khong", "phai", "nen", "dang", "theo", "thu", "tuc",
        "nhu", "the", "nao", "gi", "ve", "vay", "lam", "sao", "moi", "ma", "la",
        "giup", "da", "dang", "toi", "can", "biet", "quy", "dinh", "lam", "sao",
        "thu", "tuc", "lien", "quan", "den", "ra", "sao", "nho", "huong", "dan",
        "gium", "dum", "gup", "du", "ac", "chau", "bac", "chu", "co", "tui", "ua"}

_STATE = {"_vocab": None}


def norm_tokens(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return set(re.findall(r"[a-z0-9_]{3,}", t)) - STOP


def vocab():
    if _STATE["_vocab"] is None:
        v = set()
        for l in open("data/chunks/real_chunks.jsonl", encoding="utf-8"):
            c = json.loads(l)
            v |= norm_tokens(c.get("text", ""))
        _STATE["_vocab"] = v
    return _STATE["_vocab"]


def features(q, chunks):
    qt = norm_tokens(q["question_text"])
    gc = norm_tokens(chunks.get(q.get("source_chunk_id", ""), ""))
    nq = len(qt)
    ov = len(qt & gc)
    vcov = len(qt & vocab()) / nq if nq else 0.0
    return {"qid": q["question_id"], "nq": nq, "ov": ov, "vcov": round(vcov, 3)}


def main():
    chunks = {}
    for l in open("data/chunks/real_chunks.jsonl", encoding="utf-8"):
        c = json.loads(l)
        chunks[c["chunk_id"]] = c.get("text", "")

    labeled = [json.loads(l) for l in open("results/pha_c_labeled100.jsonl", encoding="utf-8")]
    feas = {}
    for m in labeled:
        q = json.loads(json.dumps(m))
        f = features({"question_id": m["qid"], "question_text": m["qt"],
                      "source_chunk_id": m["gold"]}, chunks)
        feas[m["qid"]] = (f, m["label"])

    grouped = {"A": [], "B": [], "C": []}
    for qid, (f, lab) in feas.items():
        grouped[lab].append(f)
    for lab, lst in grouped.items():
        if not lst:
            continue
        vc = sorted(f["vcov"] for f in lst)
        ovn = sorted(f["ov"] / f["nq"] if f["nq"] else 0.0 for f in lst)
        print(lab, "n=", len(lst),
              "| vcov median", round(vc[len(vc)//2], 3), "p25", round(vc[len(vc)//4], 3),
              "| ov/nq median", round(ovn[len(ovn)//2], 3))

    def rule_a(f):
        nq = f["nq"]
        if nq == 0:
            return True
        if f["vcov"] < 0.45:
            return True
        if f["ov"] / nq < 0.2:
            return True
        return False

    for th in [0.35, 0.45, 0.55, 0.65]:
        def rule(f):
            nq = f["nq"]
            if nq == 0:
                return True
            if f["vcov"] < th:
                return True
            if f["ov"] / nq < 0.2:
                return True
            return False
        tp = tn = fp = fn = 0
        for qid, (f, lab) in feas.items():
            pred = rule(f)
            if lab == "A":
                if pred:
                    tp += 1
                else:
                    fn += 1
            else:
                if pred:
                    fp += 1
                else:
                    tn += 1
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        print(f"threshold vcov<{th}: TP={tp} FN={fn} FP={fp} TN={tn} | prec_A={prec:.2f} rec_A={rec:.2f}")


if __name__ == "__main__":
    main()