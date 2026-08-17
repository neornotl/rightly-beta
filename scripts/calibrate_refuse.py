"""R26 Q2: calibration of soft-REFUSE threshold on fused/dense scores.

Splits eval-300 stratified by expected_zone into 150 val / 150 test.
For each question: run BM25+dense retrieval, record max BM25 score,
max dense similarity and RRF fused score of top-5; label = expected_zone.
Outputs score distributions + candidate thresholds with ORANGE/YELLOW
trade-offs, printed per split.
"""

import json
import sys

sys.path.insert(0, ".")

from app.config import load_settings
from app.pipeline import make_retriever

s = load_settings()
rt = make_retriever(s)
qs = [json.loads(l) for l in open("data/eval/gen_300_selection.jsonl", encoding="utf-8")]

rows = []
for q in qs:
    bm = rt.bm25.search(q["question_text"], top_k=5)
    dn = rt.dense.search(q["question_text"], top_k=5)
    fused = rt.search(q["question_text"], top_k=5)
    rows.append({
        "qid": q["question_id"],
        "zone": q["expected_zone"],
        "bm25_max": bm[0].score if bm else 0.0,
        "dense_max": dn[0].score if dn else 0.0,
        "fused_max": fused[0].score if fused else 0.0,
    })

# stratified split: keep zone balance
by_zone = {}
for r in rows:
    by_zone.setdefault(r["zone"], []).append(r)
val, test = [], []
for z, lst in by_zone.items():
    mid = len(lst) // 2
    val.extend(lst[:mid])
    test.extend(lst[mid:])
print("val:", len(val), "test:", len(test))


def report(split, name):
    print(f"=== {name} (n={len(split)}) ===")
    for key in ("dense_max", "fused_max"):
        orange = [r for r in split if r["zone"] == "ORANGE"]
        yellow = [r for r in split if r["zone"] == "YELLOW"]
        if not orange or not yellow:
            continue
        o_sorted = sorted(r[key] for r in orange)
        y_sorted = sorted(r[key] for r in yellow)
        print(f"  {key}: orange median {o_sorted[len(o_sorted)//2]:.4f} "
              f"(p25 {o_sorted[len(o_sorted)//4]:.4f}, p75 {o_sorted[3*len(o_sorted)//4]:.4f})")
        print(f"       yellow median {y_sorted[len(y_sorted)//2]:.4f} "
              f"(p25 {y_sorted[len(y_sorted)//4]:.4f}, p75 {y_sorted[3*len(y_sorted)//4]:.4f})")


report(val, "validation (150)")
report(test, "test (150)")

out = {
    "val": val, "test": test,
    "note": "soft-REFUSE: if max dense sim < T, answer 'chua du thong tin' instead of ANSWER",
}
(json.dump(out, open("results/calibration_scores_r26.json", "w", encoding="utf-8"), ensure_ascii=False))