"""R2 - Retrieval evaluation: top-1 accuracy, hit@k, MRR."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.retrieval.bm25_retriever import BM25Retriever
from eval.common import load_jsonl, save_csv, save_json, watermark_summary

PACKAGE_VERSION = "4.0.0"


def evaluate_retrieval(
    cases: list[dict],
    retriever: BM25Retriever,
    top_k: int = 5,
) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    hit_at = {k: 0 for k in (1, 3, 5)}
    mrr_sum = 0.0
    for idx, case in enumerate(cases):
        query = case["query"]
        expected = case["expected_source_id"]
        chunks = retriever.search(query, top_k=top_k)
        predicted = [c.source_id for c in chunks]
        top1 = predicted[0] if predicted else None
        rank = next((i + 1 for i, sid in enumerate(predicted) if sid == expected), None)
        rows.append(
            {
                "case_id": case.get("case_id", idx),
                "query": query,
                "expected_source_id": expected,
                "top1_predicted": top1 or "",
                "predicted_sources": ",".join(predicted),
                "scores": ",".join(f"{c.score:.3f}" for c in chunks),
                "hit_at_1": int(rank == 1),
                "hit_at_3": int(rank is not None and rank <= 3),
                "hit_at_5": int(rank is not None and rank <= 5),
                "mrr": (1.0 / rank) if rank else 0.0,
            }
        )
        for k in (1, 3, 5):
            if rank is not None and rank <= k:
                hit_at[k] += 1
        if rank:
            mrr_sum += 1.0 / rank
    n = len(cases)
    summary = watermark_summary(
        {
            "cases": n,
            "top1_accuracy": round(hit_at[1] / n, 4) if n else 0.0,
            "hit_at_3": round(hit_at[3] / n, 4) if n else 0.0,
            "hit_at_5": round(hit_at[5] / n, 4) if n else 0.0,
            "mrr": round(mrr_sum / n, 4) if n else 0.0,
        },
        "R2_RETRIEVAL",
        PACKAGE_VERSION,
    )
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="R2 retrieval evaluation")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, default=Path("data/chunks/demo_chunks.jsonl"))
    parser.add_argument("--output-csv", type=Path, default=Path("results/retrieval_results.csv"))
    parser.add_argument("--output-json", type=Path, default=Path("results/retrieval_summary.json"))
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    retriever = BM25Retriever.from_jsonl(args.chunks)
    rows, summary = evaluate_retrieval(load_jsonl(args.input), retriever, top_k=args.top_k)
    save_csv(args.output_csv, rows)
    save_json(args.output_json, summary)
    print(f"top-1: {summary['top1_accuracy']:.4f}, MRR: {summary['mrr']:.4f}")


if __name__ == "__main__":
    main()
