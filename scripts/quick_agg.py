import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "results/eval_1k_clean.jsonl"
rows = [json.loads(l) for l in open(path, encoding="utf-8")]
n = len(rows)
p = pa = f = 0
tot = 0.0
for r in rows:
    tot += r.get("score", 0)
    g = (r.get("grade") or "").upper()
    if g.startswith("PASS"):
        p += 1
    elif g.startswith("PARTIAL"):
        pa += 1
    elif g.startswith("FAIL"):
        f += 1
print(path)
print("pass", round(p / n, 4), "| partial", round(pa / n, 4), "| fail", round(f / n, 4), "| avg", round(tot / n, 4))