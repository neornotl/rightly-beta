import json

rows = [json.loads(l) for l in open("results/eval_1k_clean.jsonl", encoding="utf-8")]
n = len(rows)
agg = {"pass": 0, "partial": 0, "fail": 0, "tot": 0.0, "rec1": 0, "rec5": 0, "mrr": 0.0, "calls": 0, "err": 0}
cost = {}
for r in rows:
    g = (r.get("grade") or "").upper()
    s = r.get("score", 0)
    agg["tot"] += s
    if g.startswith("PASS"):
        agg["pass"] += 1
    elif g.startswith("PARTIAL"):
        agg["partial"] += 1
    elif g.startswith("FAIL"):
        agg["fail"] += 1
    if r.get("recall_at_1"):
        agg["rec1"] += 1
    if r.get("recall_at_5"):
        agg["rec5"] += 1
    agg["mrr"] += r.get("mrr", 0) or 0.0
    if r.get("error"):
        agg["err"] += 1
    u = r.get("usage") or {}
    if u:
        agg["calls"] += 1
        m = u.get("model", "?")
        c = cost.setdefault(m, {"in": 0, "out": 0})
        c["in"] += u.get("input_tokens", 0)
        c["out"] += u.get("output_tokens", 0)
print("n:", n, "| pass:", round(agg["pass"] / n, 4), "| partial:", round(agg["partial"] / n, 4),
      "| fail:", round(agg["fail"] / n, 4), "| avg:", round(agg["tot"] / n, 4))
print("recall@1:", round(agg["rec1"] / n, 4), "| recall@5:", round(agg["rec5"] / n, 4),
      "| MRR:", round(agg["mrr"] / n, 4), "| LLM calls:", agg["calls"], "| err:", agg["err"])
for m, c in cost.items():
    print("model", m, "in", c["in"], "out", c["out"])