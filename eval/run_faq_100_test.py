#!/usr/bin/env python3
"""Run 100-question test using FAQ + eval_pool questions with detailed evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.pipeline import Pipeline
from app.schemas import Zone, Action


@dataclass
class TestResult:
    question_id: str
    query: str
    category: str
    zone: str
    action: str
    answer_text: str = ""
    spoken_citation: str = ""
    source_ids: list = None
    retrieval_count: int = 0
    retrieval_sources: list = None
    latency_ms: float = 0.0
    error: str = ""
    # Evaluation metrics
    zone_correct: bool = False
    action_correct: bool = False
    has_answer: bool = False
    has_citation: bool = False
    expected_answerable: Optional[bool] = None

    def __post_init__(self):
        if self.source_ids is None:
            self.source_ids = []
        if self.retrieval_sources is None:
            self.retrieval_sources = []


def load_faq_questions() -> list[dict]:
    """Load FAQ questions."""
    project_root = Path(__file__).parent.parent
    with open(project_root / "data/faq.json", encoding='utf-8') as f:
        data = json.load(f)
    faqs = data.get('faqs', [])
    return [
        {
            "id": faq["id"],
            "query": faq["question"],
            "category": "faq",
            "expected_answerable": True,
            "expected_zone": "YELLOW",
            "expected_action": "ANSWER",
        }
        for faq in faqs
    ]


def load_eval_pool_questions(limit: int = 50) -> list[dict]:
    """Load eval pool questions."""
    project_root = Path(__file__).parent.parent
    with open(project_root / "data/eval_pool_100.json", encoding='utf-8') as f:
        data = json.load(f)
    questions = data.get('questions', [])[:limit]
    return [
        {
            "id": q["id"],
            "query": q["question"],
            "category": q.get("category", "eval"),
            "expected_answerable": True,
            "expected_zone": "YELLOW",
            "expected_action": "ANSWER",
        }
        for q in questions
    ]


def run_tests(questions: list[dict], pipeline: Pipeline) -> list[TestResult]:
    session_id = pipeline.create_session()
    results = []
    
    for i, q in enumerate(questions):
        query = q["query"]
        try:
            result = pipeline.process_text(session_id, query)
            
            sources = [c.source_id for c in result.chunks]
            
            # Determine expected
            exp_answerable = q.get("expected_answerable", True)
            exp_zone = q.get("expected_zone", "YELLOW" if exp_answerable else "ORANGE")
            exp_action = q.get("expected_action", "ANSWER" if exp_answerable else "GUIDE")
            
            r = TestResult(
                question_id=q["id"],
                query=query,
                category=q["category"],
                zone=result.decision.zone.value,
                action=result.decision.action.value,
                answer_text=result.answer.answer_text if result.answer else "",
                spoken_citation=result.answer.spoken_citation if result.answer else "",
                source_ids=result.answer.source_ids if result.answer else [],
                retrieval_count=len(result.chunks),
                retrieval_sources=sources,
                latency_ms=sum(result.latencies_ms.values()),
                expected_answerable=exp_answerable,
                # Evaluation
                zone_correct=(result.decision.zone.value == exp_zone),
                action_correct=(result.decision.action.value == exp_action),
                has_answer=bool(result.answer and result.answer.answer_text),
                has_citation=bool(result.answer and result.answer.spoken_citation),
            )
        except Exception as e:
            r = TestResult(
                question_id=q["id"],
                query=query,
                category=q["category"],
                zone="ERROR",
                action="ERROR",
                error=str(e)[:200],
            )
        results.append(r)
        
        # Progress
        status = "PASS" if r.zone_correct and r.action_correct else "FAIL"
        # Sanitize query for Windows console
        query_display = r.query[:50].encode('ascii', 'replace').decode('ascii')
        print(f"  [{i+1:3d}/{len(questions)}] {status} | {r.category:10s} | {r.zone:8s}/{r.action:7s} | {query_display}...")
    
    return results


def evaluate_results(results: list[TestResult]) -> dict:
    total = len(results)
    if total == 0:
        return {}
    
    # Overall stats
    zone_correct = sum(1 for r in results if r.zone_correct)
    action_correct = sum(1 for r in results if r.action_correct)
    has_answer = sum(1 for r in results if r.has_answer)
    has_citation = sum(1 for r in results if r.has_citation)
    errors = sum(1 for r in results if r.zone == "ERROR")
    
    # By category
    by_category = {}
    for r in results:
        cat = r.category
        if cat not in by_category:
            by_category[cat] = {"total": 0, "zone_correct": 0, "action_correct": 0, "has_answer": 0, "has_citation": 0}
        by_category[cat]["total"] += 1
        if r.zone_correct:
            by_category[cat]["zone_correct"] += 1
        if r.action_correct:
            by_category[cat]["action_correct"] += 1
        if r.has_answer:
            by_category[cat]["has_answer"] += 1
        if r.has_citation:
            by_category[cat]["has_citation"] += 1
    
    return {
        "total": total,
        "zone_correct": zone_correct,
        "zone_accuracy": zone_correct / total * 100,
        "action_correct": action_correct,
        "action_accuracy": action_correct / total * 100,
        "has_answer": has_answer,
        "answer_rate": has_answer / total * 100,
        "has_citation": has_citation,
        "citation_rate": has_citation / total * 100,
        "errors": errors,
        "by_category": by_category,
    }


def print_report(stats: dict):
    print(f"\n{'='*60}")
    print(f"100-QUESTION TEST REPORT")
    print(f"{'='*60}")
    print(f"Total questions:     {stats['total']}")
    print(f"Zone accuracy:       {stats['zone_correct']}/{stats['total']} ({stats['zone_accuracy']:.1f}%)")
    print(f"Action accuracy:     {stats['action_correct']}/{stats['total']} ({stats['action_accuracy']:.1f}%)")
    print(f"Answer rate:         {stats['has_answer']}/{stats['total']} ({stats['answer_rate']:.1f}%)")
    print(f"Citation rate:       {stats['has_citation']}/{stats['total']} ({stats['citation_rate']:.1f}%)")
    print(f"Errors:              {stats['errors']}")
    
    print(f"\nBy category:")
    for cat, data in sorted(stats['by_category'].items()):
        z = data['zone_correct'] / data['total'] * 100 if data['total'] > 0 else 0
        a = data['action_correct'] / data['total'] * 100 if data['total'] > 0 else 0
        ans = data['has_answer'] / data['total'] * 100 if data['total'] > 0 else 0
        cit = data['has_citation'] / data['total'] * 100 if data['total'] > 0 else 0
        print(f"  {cat:12s}: {data['total']:3d} q | zone={z:.0f}% | action={a:.0f}% | ans={ans:.0f}% | cit={cit:.0f}%")


def main():
    print("Loading questions...")
    faq_questions = load_faq_questions()
    eval_questions = load_eval_pool_questions(50)
    
    all_questions = faq_questions + eval_questions
    print(f"FAQ questions: {len(faq_questions)}")
    print(f"Eval questions: {len(eval_questions)}")
    print(f"Total: {len(all_questions)}")
    
    # Initialize pipeline
    settings = Settings(
        app_mode="mock",
        retrieval_backend="bm25",
        llm_backend="mock",
        tts_backend="mock",
    )
    pipeline = Pipeline(settings=settings)
    
    print("\nRunning tests...")
    results = run_tests(all_questions, pipeline)
    
    print("\nEvaluating...")
    stats = evaluate_results(results)
    print_report(stats)
    
    # Save detailed results
    output = {
        'stats': stats,
        'results': [asdict(r) for r in results]
    }
    out_path = Path(__file__).parent / "faq_100_test_results.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed results saved to: {out_path}")


if __name__ == "__main__":
    main()