#!/usr/bin/env python3
"""
Run generation benchmark on Tier 2 (1k questions) with multiple LLMs.
Requires API keys and EXECUTE_PAID_BENCHMARK=true.
"""

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import Settings
from app.llm.fallback import FallbackLLM
from app.llm.gemini_llm import GeminiLLM
from app.llm.groq_llm import GroqLLM
from app.llm.mock_llm import MockLLM
from app.retrieval.hybrid_retriever import HybridRetriever


def load_jsonl(path: Path) -> List[Dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def save_jsonl(records: List[Dict], path: Path):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


def get_available_llms(settings: Settings) -> Dict[str, Any]:
    """Get available LLM backends."""
    llms = {}

    # Always have mock
    llms["mock"] = MockLLM()

    # Check Groq
    if settings.groq_api_key:
        try:
            llms["groq"] = GroqLLM(settings)
            print("Groq LLM available")
        except Exception as e:
            print(f"Groq LLM failed: {e}")

    # Check Gemini
    if settings.gemini_api_key:
        try:
            llms["gemini"] = GeminiLLM(settings)
            print("Gemini LLM available")
        except Exception as e:
            print(f"Gemini LLM failed: {e}")

    # Fallback
    if len(llms) > 1:
        llms["fallback"] = FallbackLLM(settings)

    return llms


def run_generation_benchmark(
    questions: List[Dict],
    llms: Dict,
    retriever: HybridRetriever,
    output_dir: Path,
    max_per_model: int = None,
) -> Dict[str, List[Dict]]:
    """Run generation benchmark for each LLM."""

    # Filter to ANSWER questions only
    answer_questions = [q for q in questions if q.get("expected_answerability") == "ANSWER"]
    if max_per_model:
        answer_questions = answer_questions[:max_per_model]

    print(f"Running generation on {len(answer_questions)} ANSWER questions...")

    all_results = {}

    for model_name, llm in llms.items():
        print(f"\nTesting {model_name}...")
        results = []

        for i, q in enumerate(answer_questions):
            query = q["question_text"]
            expected_sids = q.get("expected_source_ids", [])

            # Retrieve chunks
            chunks = retriever.search(query, top_k=5)

            # Generate answer
            start = time.perf_counter()
            try:
                answer = llm.generate_answer(query, chunks)
                latency_ms = (time.perf_counter() - start) * 1000

                results.append(
                    {
                        "question_id": q["question_id"],
                        "model": model_name,
                        "query": query,
                        "answer": answer,
                        "retrieved_chunks": [
                            {"source_id": c.source_id, "score": c.score} for c in chunks
                        ],
                        "expected_source_ids": expected_sids,
                        "latency_ms": latency_ms,
                        "error": None,
                    }
                )
            except Exception as e:
                latency_ms = (time.perf_counter() - start) * 1000
                results.append(
                    {
                        "question_id": q["question_id"],
                        "model": model_name,
                        "query": query,
                        "answer": None,
                        "retrieved_chunks": [
                            {"source_id": c.source_id, "score": c.score} for c in chunks
                        ],
                        "expected_source_ids": expected_sids,
                        "latency_ms": latency_ms,
                        "error": f"{type(e).__name__}: {str(e)[:200]}",
                    }
                )

            if (i + 1) % 50 == 0:
                print(f"  Completed {i + 1}/{len(answer_questions)}")

        all_results[model_name] = results
        save_jsonl(results, output_dir / f"generation_{model_name}.jsonl")

    return all_results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run Tier 2 generation benchmark")
    parser.add_argument("--input", required=True, help="Input tier2 JSONL file")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--max-per-model", type=int, default=None, help="Limit questions per model")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without API calls")
    args = parser.parse_args()

    # Check budget flag
    if not args.dry_run and not os.environ.get("EXECUTE_PAID_BENCHMARK"):
        print("ERROR: EXECUTE_PAID_BENCHMARK=true not set. Use --dry-run or set env var.")
        sys.exit(1)

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading questions from {input_path}...")
    questions = load_jsonl(input_path)
    print(f"Total questions: {len(questions)}")

    # Initialize components
    settings = Settings()
    retriever = HybridRetriever(settings)

    if args.dry_run:
        print("DRY RUN: Using MockLLM only")
        llms = {"mock": MockLLM()}
    else:
        llms = get_available_llms(settings)
        if len(llms) <= 1:
            print(
                "WARNING: Only MockLLM available. Set GROQ_API_KEY and/or GEMINI_API_KEY for real models."
            )

    print(f"Available models: {list(llms.keys())}")

    # Run benchmark
    results = run_generation_benchmark(questions, llms, retriever, output_dir, args.max_per_model)

    # Save combined
    all_results = []
    for model_results in results.values():
        all_results.extend(model_results)
    save_jsonl(all_results, output_dir / "generation_all_models.jsonl")

    # Print summary
    print("\n" + "=" * 60)
    print("GENERATION BENCHMARK SUMMARY")
    print("=" * 60)
    for model_name, model_results in results.items():
        successful = [r for r in model_results if not r["error"]]
        failed = [r for r in model_results if r["error"]]
        avg_latency = (
            sum(r["latency_ms"] for r in successful) / len(successful) if successful else 0
        )
        print(f"\n{model_name}:")
        print(f"  Total: {len(model_results)}")
        print(f"  Successful: {len(successful)}")
        print(f"  Failed: {len(failed)}")
        print(f"  Avg latency: {avg_latency:.1f}ms")
        if failed:
            print(f"  Errors: {defaultdict(int, {(r['error'][:50], 1) for r in failed})}")


if __name__ == "__main__":
    main()
