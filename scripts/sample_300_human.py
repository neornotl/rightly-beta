import json
import random
import os
import sys

sys.path.insert(0, os.path.abspath("."))

rows = [json.loads(l) for l in open("results/eval_1k_clean.jsonl", encoding="utf-8")]

# stratify by zone + difficulty
by_key = {}
for r in rows:
    k = (r.get("expected_zone", "?"), r.get("difficulty", "?"))
    by_key.setdefault(k, []).append(r)

random.seed(20260814)
n = 300
chosen = []
for k, lst in sorted(by_key.items()):
    need = max(1, round(len(lst) / len(rows) * n))
    random.shuffle(lst)
    chosen.extend(lst[:need])

random.shuffle(chosen)
chosen = chosen[:n]

# save eval pack for human/LLM evaluator
eval_pack = []
for r in chosen:
    eval_pack.append({
        "question_id": r["question_id"],
        "question_text": r["question_text"],
        "expected_zone": r.get("expected_zone"),
        "expected_action": r.get("expected_action"),
        "expected_source_ids": r.get("expected_source_ids", []),
        "auto_grade": r.get("grade"),
        "auto_score": r.get("score"),
        "answer_text": r.get("answer_text"),
        "source_ids": r.get("source_ids", []),
        "retrieved_ids": r.get("retrieved_ids", []),
        "recall_at_1": r.get("recall_at_1"),
        "recall_at_5": r.get("recall_at_5"),
    })

with open("results/eval_300_for_human.jsonl", "w", encoding="utf-8") as f:
    for x in eval_pack:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")

print("saved 300 samples to results/eval_300_for_human.jsonl")
zc = {}
dc = {}
for x in eval_pack:
    zc[x["expected_zone"]] = zc.get(x["expected_zone"], 0) + 1
    dc[x["auto_grade"]] = dc.get(x["auto_grade"], 0) + 1
print("zone dist:", zc)
print("auto grade dist:", dc)