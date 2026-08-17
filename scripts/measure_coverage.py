"""R26 Step 0: measure candidate coverage (retrieval bottleneck analysis).

Runs on questions with gold sources only. For each query:
  - BM25-only recall at pools 10/20/40/80
  - dense-only recall at pools 10/20/40/80
  - union (BM25 ∪ dense) recall at pools 10/20/40/80
  - fused (RRF, current pipeline) recall at top-5/top-12

Output: per-pool coverage table + sparse/dense contribution stats.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.pipeline import make_retriever

POOLS = (10, 20, 40, 80)


def matches(cids, expected) -> bool:
    return any(e in cid for cid in cids for e in expected)


def main() -> int:
    s = load_settings()
    rt = make_retriever(s)
    questions = [json.loads(l) for l in
                 (ROOT / "data/eval/gen_10k_realistic.jsonl").open(encoding="utf-8")]
    sample = [q for q in questions if q.get("expected_source_ids")]
    sample = sample[:2000]
    print(f"sample: {len(sample)} questions with gold sources (first 2000)")
    t0 = time.perf_counter()
    stats = {
        "bm25": {p: 0 for p in POOLS},
        "dense": {p: 0 for p in POOLS},
        "union": {p: 0 for p in POOLS},
        "fused5": 0, "fused12": 0,
    }
    for i, q in enumerate(sample):
        exp = q["expected_source_ids"]
        bm = rt.bm25.search(q["question_text"], top_k=POOLS[-1])
        dn = rt.dense.search(q["question_text"], top_k=POOLS[-1])
        bm_ids = [c.chunk_id for c in bm]
        dn_ids = [c.chunk_id for c in dn]
        if matches(bm_ids, exp) or matches(dn_ids, exp):
            pass
        for p in POOLS:
            stats["bm25"][p] += int(matches(bm_ids[:p], exp))
            stats["dense"][p] += int(matches(dn_ids[:p], exp))
            stats["union"][p] += int(matches((bm_ids + dn_ids)[:p * 2], exp))
        fused = rt.search(q["question_text"], top_k=12)
        fids = [c.chunk_id for c in fused]
        stats["fused5"] += int(matches(fids[:5], exp))
        stats["fused12"] += int(matches(fids[:12], exp))
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(sample)} ({round(time.perf_counter() - t0, 1)}s)")
    n = len(sample)
    print("\n=== COVERAGE (recall of gold source within candidate pool) ===")
    print(f"{'pool':>6} | {'bm25':>6} | {'dense':>6} | {'union':>6}")
    for p in POOLS:
        print(f"{p:>6} | {stats['bm25'][p] / n:>6.3f} | {stats['dense'][p] / n:>6.3f}"
              f" | {stats['union'][p] / n:>6.3f}")
    print(f"\nfused top-5 recall:  {stats['fused5'] / n:.3f}")
    print(f"fused top-12 recall: {stats['fused12'] / n:.3f}")
    out = ROOT / "results/retrieval_coverage_r26.json"
    out.write_text(json.dumps({"n": n, **stats, "seconds": round(time.perf_counter() - t0, 1)},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())