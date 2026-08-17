"""R20 answer-quality metrics for the real legal corpus.

Council Round 20 priority #2 (2026-08-13):
  1. Retrieval Faithfulness  — the LLM answer must cite sources that were
     actually retrieved (no hallucinated source_ids). Computed per answer as
     the fraction of cited sources present in the retrieved top-k.
  2. Numeric Accuracy        — claim numbers (salaries, ages, fines, dates)
     in the answer text appear verbatim in a cited source chunk.
  3. Latency summary         — retrieval + total pipeline ms.

Not a replacement for the manual 165-case rubric review in
docs/quality_evaluation_report.md — a cheap automated smoke/regression gate.

Usage:
    python -m eval.answer_quality --input data/eval/answer_quality.jsonl
    python -m eval.answer_quality --input data/eval/answer_quality.jsonl \
        --retrieval hybrid --mode mock
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from eval.common import load_jsonl, median, percentile, save_csv, save_json, watermark_summary

PACKAGE_VERSION = "1.0.0"

_NUM_RE = re.compile(r"\d[\d.,]*")


def _numbers(text: str) -> set[str]:
    """Numbers in ``text`` normalized (1.000.000 == 1,000,000)."""
    out: set[str] = set()
    for tok in _NUM_RE.findall(text.replace("\u00a0", "")):
        norm = tok.replace(".", "").replace(",", "")
        if norm.isdigit():
            out.add(norm)
    return out


def retrieval_faithfulness(cited: list[str], retrieved: set[str]) -> float:
    """Fraction of cited source_ids present in retrieved top-k."""
    if not cited:
        return 0.0
    return sum(1 for sid in cited if sid in retrieved) / len(cited)


def numeric_accuracy(answer_text: str, cited_chunks: list[str]) -> float:
    """Fraction of claim numbers backed up by a cited source chunk."""
    nums = _numbers(answer_text)
    if not nums:
        return 1.0  # no numeric claims -> vacuously accurate
    supported = 0
    for n in nums:
        if any(n in _numbers(chunk) for chunk in cited_chunks):
            supported += 1
    return supported / len(nums)


def evaluate(
    cases: list[dict],
    *,
    pipeline,
    top_k: int = 5,
) -> tuple[list[dict], dict]:
    """Run the pipeline over cases and compute answer-quality metrics.

    Case schema (see data/eval/answer_quality.schema.json):
        {"case_id", "query", "expected_source_id" (optional), "reference_answer" (optional)}
    """
    rows: list[dict] = []
    agg = defaultdict(
        lambda: {"n": 0, "faith_ok": 0, "num_ok": 0, "answered": 0, "faith": [], "num": []}
    )

    for case in cases:
        q = case["query"]
        cat = case.get("category", "general")
        a = agg[cat]
        a["n"] += 1

        t0 = time.perf_counter()
        chunks = pipeline.retriever.search(q, top_k=top_k)
        lat_retr = (time.perf_counter() - t0) * 1000.0

        tid = pipeline.create_session()
        t0 = time.perf_counter()
        result = pipeline.process_text(tid, q)
        lat_total = (time.perf_counter() - t0) * 1000.0

        answer = result.answer
        retrieved = {c.source_id for c in chunks}
        row: dict = {
            "case_id": case.get("case_id", ""),
            "category": cat,
            "query": q,
            "answered": int(answer is not None),
            "retrieved_sources": ",".join(sorted(retrieved)),
            "latency_retrieval_ms": round(lat_retr, 1),
            "latency_total_ms": round(lat_total, 1),
        }
        if answer is not None:
            a["answered"] += 1
            cited = [s for s in answer.source_ids if s]
            row["cited_sources"] = ",".join(cited)
            row["answer_text"] = answer.answer_text[:400]

            faith = retrieval_faithfulness(cited, retrieved)
            a["faith"].append(faith)
            if faith >= 1.0:
                a["faith_ok"] += 1
            row["retrieval_faithfulness"] = round(faith, 4)

            # Numeric accuracy against cited chunks' text.
            cited_chunks = [c.text for c in chunks if c.source_id in set(cited)]
            num = numeric_accuracy(answer.answer_text, cited_chunks)
            a["num"].append(num)
            if num >= 1.0:
                a["num_ok"] += 1
            row["numeric_accuracy"] = round(num, 4)
        rows.append(row)

    summary: dict = {"cases": len(cases), "by_category": {}}
    for cat, m in sorted(agg.items()):
        n = m["n"]
        summary["by_category"][cat] = {
            "n": n,
            "answer_rate": round(m["answered"] / n, 4),
            "retrieval_faithfulness_mean": round(sum(m["faith"]) / len(m["faith"]), 4)
            if m["faith"]
            else None,
            "retrieval_faithfulness_100pct": round(m["faith_ok"] / n, 4),
            "numeric_accuracy_mean": round(sum(m["num"]) / len(m["num"]), 4) if m["num"] else None,
            "numeric_accuracy_100pct": round(m["num_ok"] / n, 4),
        }
    lats_r = [r["latency_retrieval_ms"] for r in rows]
    lats_t = [r["latency_total_ms"] for r in rows]
    summary["retrieval_latency_ms"] = {
        "p50": round(median(lats_r), 1),
        "p95": round(percentile(lats_r, 95), 1),
    }
    summary["total_latency_ms"] = {
        "p50": round(median(lats_t), 1),
        "p95": round(percentile(lats_t, 95), 1),
    }
    return rows, watermark_summary(summary, "R20_ANSWER_QUALITY", PACKAGE_VERSION)


def main() -> None:
    parser = argparse.ArgumentParser(description="R20 answer-quality metrics")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, default=Path("results/answer_quality.csv"))
    parser.add_argument(
        "--output-json", type=Path, default=Path("results/answer_quality_summary.json")
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--retrieval", default="hybrid", choices=["bm25", "hybrid"])
    parser.add_argument("--mode", default="mock", choices=["mock", "cloud"])
    args = parser.parse_args()

    import os

    os.environ["RETRIEVAL_BACKEND"] = args.retrieval
    os.environ["LLM_BACKEND"] = (
        "mock" if args.mode == "mock" else os.environ.get("LLM_BACKEND", "groq")
    )
    os.environ["TTS_BACKEND"] = "mock"
    os.environ["APP_MODE"] = "mock" if args.mode == "mock" else "cloud"

    from app.config import load_settings
    from app.pipeline import Pipeline

    pipe = Pipeline(load_settings())
    cases = load_jsonl(args.input)
    rows, summary = evaluate(cases, pipeline=pipe, top_k=args.top_k)
    save_csv(args.output_csv, rows)
    save_json(args.output_json, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
