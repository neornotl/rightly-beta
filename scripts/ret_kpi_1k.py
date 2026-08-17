import json

qs = {json.loads(l)["question_id"]: json.loads(l) for l in open("data/eval/gen_1k_clean.jsonl", encoding="utf-8")}
rows = [json.loads(l) for l in open("results/eval_1k_clean.jsonl", encoding="utf-8")]
wg = [r for r in rows if qs[r["question_id"]].get("expected_source_ids") and qs[r["question_id"]].get("source_chunk_id")]
n = len(wg)
r1 = sum(1 for r in wg if r.get("recall_at_1"))
r3 = sum(1 for r in wg if r.get("recall_at_3"))
r5 = sum(1 for r in wg if r.get("recall_at_5"))
mrr = sum((r.get("mrr") or 0.0) for r in wg) / n
print("with-gold n:", n)
print("recall@1:", round(r1 / n, 4), "| recall@3:", round(r3 / n, 4), "| recall@5:", round(r5 / n, 4), "| MRR:", round(mrr, 4))