import json
import random
import os
import sys
import csv

sys.path.insert(0, os.path.abspath("."))

# Load 300 stratified items
items_300 = [json.loads(l) for l in open("results/eval_300_for_human.jsonl", encoding="utf-8")]

# Load full 10k to get more RED items
all_10k = [json.loads(l) for l in open("data/eval/gen_10k_realistic.jsonl", encoding="utf-8")]
red_pool = [q for q in all_10k if q.get("expected_zone") == "RED" and q.get("expected_action") in ("REFUSE", "ESCALATE")]
ids_300 = set(i["question_id"] for i in items_300)
red_new = [q for q in red_pool if q["question_id"] not in ids_300]

random.seed(20260814)
random.shuffle(red_new)
red_oversample = red_new[:50]  # Take 50 from 10k

print(f"300 items: {len(items_300)}")
print(f"RED oversample: {len(red_oversample)}")

# Combine
all_350 = items_300 + red_oversample
random.shuffle(all_350)

# Load eval results for answers
eval_res = [json.loads(l) for l in open("results/eval_10k_text.jsonl", encoding="utf-8")]
eval_map = {r["question_id"]: r for r in eval_res}

# Prepare annotation format (blind)
annot_items = []
for i, item in enumerate(all_350):
    r = eval_map.get(item["question_id"], {})
    answer_text = r.get("answer_text", "")
    # If no eval result (oversample from 10k not in 1k), run quick eval? 
    # For now, use what we have
    if not answer_text:
        # Try 1k clean results
        eval_1k = [json.loads(l) for l in open("results/eval_1k_clean.jsonl", encoding="utf-8")]
        eval_1k_map = {r["question_id"]: r for r in eval_1k}
        r = eval_1k_map.get(item["question_id"], {})
        answer_text = r.get("answer_text", "")
    
    annot_items.append({
        "item_id": f"P4_{i+1:03d}",
        "question_id": item["question_id"],
        "question_text": item["question_text"],
        "answer_text": answer_text,
        "retrieved_chunks": r.get("retrieved_ids", []),
        "answer_type": r.get("action", "ANSWER"),
        # Blind fields (NOT shown to annotators):
        "_expected_zone": item.get("expected_zone"),
        "_expected_action": item.get("expected_action"),
        "_expected_source_ids": item.get("expected_source_ids", []),
        "_auto_grade": r.get("grade"),
        "_auto_score": r.get("score"),
    })

# Save JSONL
with open("results/p4_annotation_items.jsonl", "w", encoding="utf-8") as f:
    for item in annot_items:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

# Save CSV for Excel annotation
fieldnames = ["item_id", "question_id", "question_text", "answer_text", "retrieved_chunks", "answer_type"]
with open("results/p4_annotation_items.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for item in annot_items:
        row = {k: item[k] for k in fieldnames}
        row["retrieved_chunks"] = "; ".join(row["retrieved_chunks"])
        writer.writerow(row)

# Stats
zones = {}
for item in annot_items:
    z = item["_expected_zone"]
    zones[z] = zones.get(z, 0) + 1
print(f"Total: {len(annot_items)}")
print(f"Zone dist: {zones}")

# Save key for later analysis
with open("results/p4_annotation_key.jsonl", "w", encoding="utf-8") as f:
    for item in annot_items:
        f.write(json.dumps({
            "item_id": item["item_id"],
            "question_id": item["question_id"],
            "expected_zone": item["_expected_zone"],
            "expected_action": item["_expected_action"],
            "expected_source_ids": item["_expected_source_ids"],
            "auto_grade": item["_auto_grade"],
            "auto_score": item["_auto_score"],
        }, ensure_ascii=False) + "\n")

print("Saved: p4_annotation_items.jsonl, .csv, and key")