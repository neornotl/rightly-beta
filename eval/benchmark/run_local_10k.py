#!/usr/bin/env python3
"""
Run Tier 1 local benchmark (10k questions) - no cloud LLM calls.
Tests: retrieval, answerability, routing, citation validation, metadata.
"""

import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import Settings
from app.retrieval.hybrid_retriever import HybridRetriever
from app.safety.router import SafetyRouter
from app.validation.citation_validator import CitationValidator


def load_jsonl(path: Path) -> List[Dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def save_jsonl(records: List[Dict], path: Path):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


def run_retrieval_benchmark(questions: List[Dict], retriever: HybridRetriever) -> List[Dict]:
    """Run retrieval on all questions."""
    results = []
    for q in questions:
        query = q["question_text"]
        expected_sids = set(q.get("expected_source_ids", []))

        start = time.perf_counter()
        chunks = retriever.search(query, top_k=5)
        latency_ms = (time.perf_counter() - start) * 1000

        retrieved_sids = [c.source_id for c in chunks]

        # Calculate metrics
        recall_at_5 = (
            len(set(retrieved_sids) & expected_sids) / len(expected_sids)
            if expected_sids
            else (1.0 if not retrieved_sids else 0.0)
        )

        # nDCG@5
        dcg = 0.0
        for i, sid in enumerate(retrieved_sids[:5]):
            if sid in expected_sids:
                dcg += 1.0 / (i + 1)  # Simplified: 1/log2(rank+1) approx
        ideal = sum(1.0 / (i + 1) for i in range(min(5, len(expected_sids))))
        ndcg_at_5 = dcg / ideal if ideal > 0 else 1.0

        results.append(
            {
                "question_id": q["question_id"],
                "query": query,
                "retrieved_source_ids": retrieved_sids,
                "expected_source_ids": list(expected_sids),
                "recall_at_5": recall_at_5,
                "ndcg_at_5": ndcg_at_5,
                "latency_ms": latency_ms,
                "empty_retrieval": len(chunks) == 0,
            }
        )
    return results


def run_routing_benchmark(questions: List[Dict], router: SafetyRouter) -> List[Dict]:
    """Run safety routing on all questions."""
    results = []
    for q in questions:
        query = q["question_text"]
        expected_zone = q.get("expected_zone", "YELLOW")
        expected_action = q.get("expected_answerability", "ANSWER")

        # Mock chunks for routing test
        from app.retrieval.base import RetrievedChunk

        chunks = [
            RetrievedChunk(chunk_id=f"mock::{i}", source_id="mock", text="mock", score=5.0)
            for i in range(3)
        ]

        start = time.perf_counter()
        decision, _ = router.route(query, chunks)
        latency_ms = (time.perf_counter() - start) * 1000

        zone_correct = decision.zone.value == expected_zone
        action_correct = decision.action.value == expected_action

        results.append(
            {
                "question_id": q["question_id"],
                "query": query,
                "expected_zone": expected_zone,
                "predicted_zone": decision.zone.value,
                "expected_action": expected_action,
                "predicted_action": decision.action.value,
                "zone_correct": zone_correct,
                "action_correct": action_correct,
                "reason_codes": decision.reason_codes,
                "latency_ms": latency_ms,
            }
        )
    return results


def run_citation_benchmark(questions: List[Dict], validator: CitationValidator) -> List[Dict]:
    """Run citation validation on ANSWER questions."""
    from app.schemas import GroundedAnswer

    results = []

    answer_questions = [q for q in questions if q.get("expected_answerability") == "ANSWER"]

    for q in answer_questions:
        expected_sids = set(q.get("expected_source_ids", []))
        cited_sids = q.get("expected_source_ids", [])  # Gold cites expected sources

        answer = GroundedAnswer(
            answer_text="mock answer",
            spoken_citation="mock citation",
            source_ids=cited_sids,
            limitations=[],
            next_step="",
        )

        start = time.perf_counter()
        verdict = validator.validate(answer, expected_sids)
        latency_ms = (time.perf_counter() - start) * 1000

        results.append(
            {
                "question_id": q["question_id"],
                "cited_source_ids": cited_sids,
                "retrieved_source_ids": list(expected_sids),
                "verdict_ok": verdict.ok,
                "issues": [{"kind": i.kind, "source_id": i.source_id} for i in verdict.issues],
                "latency_ms": latency_ms,
            }
        )
    return results


def run_answerability_benchmark(questions: List[Dict], retriever: HybridRetriever) -> List[Dict]:
    """Test answerability gate."""
    results = []
    for q in questions:
        query = q["question_text"]
        expected = q.get("expected_answerability", "ANSWER")

        start = time.perf_counter()
        chunks = retriever.search(query, top_k=5)
        latency_ms = (time.perf_counter() - start) * 1000

        # Apply answerability gate
        bm25_top1 = max((c.score for c in chunks if hasattr(c, "score")), default=0)
        dense_top1 = 0  # Would need dense scores

        gate_pass = bm25_top1 >= 12.2 or dense_top1 >= 0.88
        predicted = "ANSWER" if gate_pass else "REFUSE"

        # Map expected
        expected_binary = "ANSWER" if expected == "ANSWER" else "REFUSE"
        correct = predicted == expected_binary

        results.append(
            {
                "question_id": q["question_id"],
                "query": query,
                "expected": expected,
                "predicted": predicted,
                "correct": correct,
                "bm25_top1": bm25_top1,
                "chunks_retrieved": len(chunks),
                "latency_ms": latency_ms,
            }
        )
    return results


def aggregate_results(
    retrieval_results: List[Dict],
    routing_results: List[Dict],
    citation_results: List[Dict],
    answerability_results: List[Dict],
) -> Dict[str, Any]:
    """Aggregate all metrics."""

    # Retrieval metrics
    total_ret = len(retrieval_results)
    recall_5 = sum(r["recall_at_5"] for r in retrieval_results) / total_ret if total_ret else 0
    ndcg_5 = sum(r["ndcg_at_5"] for r in retrieval_results) / total_ret if total_ret else 0
    empty_rate = (
        sum(1 for r in retrieval_results if r["empty_retrieval"]) / total_ret if total_ret else 0
    )
    avg_latency_ret = (
        sum(r["latency_ms"] for r in retrieval_results) / total_ret if total_ret else 0
    )

    # Routing metrics
    total_rout = len(routing_results)
    zone_acc = (
        sum(1 for r in routing_results if r["zone_correct"]) / total_rout if total_rout else 0
    )
    action_acc = (
        sum(1 for r in routing_results if r["action_correct"]) / total_rout if total_rout else 0
    )
    avg_latency_rout = (
        sum(r["latency_ms"] for r in routing_results) / total_rout if total_rout else 0
    )

    # Confusion matrix
    zone_confusion = defaultdict(lambda: defaultdict(int))
    action_confusion = defaultdict(lambda: defaultdict(int))
    for r in routing_results:
        zone_confusion[r["expected_zone"]][r["predicted_zone"]] += 1
        action_confusion[r["expected_action"]][r["predicted_action"]] += 1

    # Citation metrics
    total_cit = len(citation_results)
    cit_pass = sum(1 for r in citation_results if r["verdict_ok"]) / total_cit if total_cit else 0
    avg_latency_cit = sum(r["latency_ms"] for r in citation_results) / total_cit if total_cit else 0

    # Answerability metrics
    total_ans = len(answerability_results)
    ans_precision = (
        sum(1 for r in answerability_results if r["correct"] and r["predicted"] == "ANSWER")
        / sum(1 for r in answerability_results if r["predicted"] == "ANSWER")
        if any(r["predicted"] == "ANSWER" for r in answerability_results)
        else 0
    )
    ans_recall = (
        sum(1 for r in answerability_results if r["correct"] and r["expected"] == "ANSWER")
        / sum(1 for r in answerability_results if r["expected"] == "ANSWER")
        if any(r["expected"] == "ANSWER" for r in answerability_results)
        else 0
    )
    ans_f1 = (
        2 * ans_precision * ans_recall / (ans_precision + ans_recall)
        if (ans_precision + ans_recall) > 0
        else 0
    )
    false_accept = sum(
        1 for r in answerability_results if r["predicted"] == "ANSWER" and r["expected"] != "ANSWER"
    )
    false_reject = sum(
        1 for r in answerability_results if r["predicted"] != "ANSWER" and r["expected"] == "ANSWER"
    )

    return {
        "retrieval": {
            "total": total_ret,
            "mean_recall_at_5": recall_5,
            "mean_ndcg_at_5": ndcg_5,
            "empty_retrieval_rate": empty_rate,
            "avg_latency_ms": avg_latency_ret,
        },
        "routing": {
            "total": total_rout,
            "zone_accuracy": zone_acc,
            "action_accuracy": action_acc,
            "avg_latency_ms": avg_latency_rout,
            "zone_confusion": {k: dict(v) for k, v in zone_confusion.items()},
            "action_confusion": {k: dict(v) for k, v in action_confusion.items()},
        },
        "citation": {"total": total_cit, "pass_rate": cit_pass, "avg_latency_ms": avg_latency_cit},
        "answerability": {
            "total": total_ans,
            "precision": ans_precision,
            "recall": ans_recall,
            "f1": ans_f1,
            "false_accept": false_accept,
            "false_reject": false_reject,
        },
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run Tier 1 local 10k benchmark")
    parser.add_argument("--input", required=True, help="Input tier1 JSONL file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--max-questions", type=int, default=None, help="Limit questions for testing"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading questions from {input_path}...")
    questions = load_jsonl(input_path)
    if args.max_questions:
        questions = questions[: args.max_questions]
    print(f"Running benchmark on {len(questions)} questions...")

    # Initialize components
    print("Initializing components...")
    from app.pipeline import make_retriever
    settings = Settings()
    retriever = make_retriever(settings)
    router = SafetyRouter(settings)
    validator = CitationValidator()

    # Run benchmarks
    print("\n1. Running retrieval benchmark...")
    retrieval_results = run_retrieval_benchmark(questions, retriever)
    save_jsonl(retrieval_results, output_dir / "retrieval_results.jsonl")

    print("2. Running routing benchmark...")
    routing_results = run_routing_benchmark(questions, router)
    save_jsonl(routing_results, output_dir / "routing_results.jsonl")

    print("3. Running citation benchmark...")
    citation_results = run_citation_benchmark(questions, validator)
    save_jsonl(citation_results, output_dir / "citation_results.jsonl")

    print("4. Running answerability benchmark...")
    answerability_results = run_answerability_benchmark(questions, retriever)
    save_jsonl(answerability_results, output_dir / "answerability_results.jsonl")

    # Aggregate
    print("\nAggregating results...")
    summary = aggregate_results(
        retrieval_results, routing_results, citation_results, answerability_results
    )

    summary_path = output_dir / "local_10k_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Summary saved to {summary_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("TIER 1 LOCAL 10K BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"Questions: {len(questions)}")
    print("\nRetrieval:")
    print(f"  Recall@5: {summary['retrieval']['mean_recall_at_5']:.4f}")
    print(f"  nDCG@5:   {summary['retrieval']['mean_ndcg_at_5']:.4f}")
    print(f"  Empty rate: {summary['retrieval']['empty_retrieval_rate']:.4f}")
    print(f"  Avg latency: {summary['retrieval']['avg_latency_ms']:.1f}ms")

    print("\nRouting:")
    print(f"  Zone accuracy: {summary['routing']['zone_accuracy']:.4f}")
    print(f"  Action accuracy: {summary['routing']['action_accuracy']:.4f}")
    print(f"  Avg latency: {summary['routing']['avg_latency_ms']:.1f}ms")

    print("\nCitation:")
    print(f"  Pass rate: {summary['citation']['pass_rate']:.4f}")
    print(f"  Avg latency: {summary['citation']['avg_latency_ms']:.1f}ms")

    print("\nAnswerability:")
    print(f"  Precision: {summary['answerability']['precision']:.4f}")
    print(f"  Recall: {summary['answerability']['recall']:.4f}")
    print(f"  F1: {summary['answerability']['f1']:.4f}")
    print(f"  False accept: {summary['answerability']['false_accept']}")
    print(f"  False reject: {summary['answerability']['false_reject']}")


if __name__ == "__main__":
    main()
