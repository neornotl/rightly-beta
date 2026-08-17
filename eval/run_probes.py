#!/usr/bin/env python3
"""Probe runner for regression detection."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.pipeline import Pipeline


@dataclass
class ProbeResult:
    probe_id: str
    query: str
    zone: str
    action: str
    answer_text: str = ""
    spoken_citation: str = ""
    source_ids: list = None
    retrieval_count: int = 0
    retrieval_sources: list = None
    latency_ms: float = 0.0
    error: str = ""

    def __post_init__(self):
        if self.source_ids is None:
            self.source_ids = []
        if self.retrieval_sources is None:
            self.retrieval_sources = []


def load_probes(path: Path) -> list[dict]:
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return data.get('probes', [])


def run_probes(probes: list[dict], pipeline: Pipeline) -> list[ProbeResult]:
    session_id = pipeline.create_session()
    results = []
    
    for probe in probes:
        query = probe['query']
        try:
            result = pipeline.process_text(session_id, query)
            
            sources = [c.source_id for c in result.chunks]
            
            r = ProbeResult(
                probe_id=probe['id'],
                query=query,
                zone=result.decision.zone.value,
                action=result.decision.action.value,
                answer_text=result.answer.answer_text if result.answer else "",
                spoken_citation=result.answer.spoken_citation if result.answer else "",
                source_ids=result.answer.source_ids if result.answer else [],
                retrieval_count=len(result.chunks),
                retrieval_sources=sources,
                latency_ms=sum(result.latencies_ms.values()),
            )
        except Exception as e:
            r = ProbeResult(
                probe_id=probe['id'],
                query=query,
                zone="ERROR",
                action="ERROR",
                error=str(e)[:200],
            )
        results.append(r)
        print(f"  {probe['id']}: {r.zone}/{r.action} | retrieval={r.retrieval_count} | ans={'Y' if r.answer_text else 'N'}")
    
    return results


def evaluate_baseline(results: list[ProbeResult], probes: list[dict]) -> dict:
    """Compare results against probe expectations."""
    probe_map = {p['id']: p for p in probes}
    stats = {
        'total': len(results),
        'zone_correct': 0,
        'action_correct': 0,
        'answerable_correct': 0,
        'has_answer': 0,
        'has_citation': 0,
        'details': []
    }
    
    for r in results:
        probe = probe_map.get(r.probe_id, {})
        exp_zone = "YELLOW" if probe.get('expected_answerable') else "ORANGE"
        exp_action = "ANSWER" if probe.get('expected_answerable') else "GUIDE"
        
        zone_ok = r.zone == exp_zone
        action_ok = r.action == exp_action
        answerable_ok = (r.zone == "YELLOW") == probe.get('expected_answerable', False)
        
        if zone_ok:
            stats['zone_correct'] += 1
        if action_ok:
            stats['action_correct'] += 1
        if answerable_ok:
            stats['answerable_correct'] += 1
        if r.answer_text:
            stats['has_answer'] += 1
        if r.spoken_citation:
            stats['has_citation'] += 1
        
        stats['details'].append({
            'probe_id': r.probe_id,
            'zone': r.zone,
            'expected_zone': exp_zone,
            'zone_ok': zone_ok,
            'action': r.action,
            'expected_action': exp_action,
            'action_ok': action_ok,
            'has_answer': bool(r.answer_text),
            'has_citation': bool(r.spoken_citation),
            'retrieval_count': r.retrieval_count,
            'source_ids': r.source_ids,
            'error': r.error
        })
    
    return stats


def main():
    probe_path = Path(__file__).parent / "probe_questions.json"
    if not probe_path.exists():
        print(f"Probe file not found: {probe_path}")
        sys.exit(1)
    
    probes = load_probes(probe_path)
    print(f"Loaded {len(probes)} probes")
    
    # Initialize pipeline with mock settings for baseline
    settings = Settings(
        app_mode="mock",
        retrieval_backend="bm25",  # Use BM25 for speed, no dense index needed
        llm_backend="mock",
        tts_backend="mock",
    )
    pipeline = Pipeline(settings=settings)
    
    print("\nRunning probes...")
    results = run_probes(probes, pipeline)
    
    print("\nEvaluating...")
    stats = evaluate_baseline(results, probes)
    
    print(f"\n=== BASELINE RESULTS ===")
    print(f"Total probes: {stats['total']}")
    print(f"Zone correct: {stats['zone_correct']}/{stats['total']} ({stats['zone_correct']/stats['total']*100:.1f}%)")
    print(f"Action correct: {stats['action_correct']}/{stats['total']} ({stats['action_correct']/stats['total']*100:.1f}%)")
    print(f"Answerable correct: {stats['answerable_correct']}/{stats['total']} ({stats['answerable_correct']/stats['total']*100:.1f}%)")
    print(f"Has answer: {stats['has_answer']}/{stats['total']}")
    print(f"Has citation: {stats['has_citation']}/{stats['total']}")
    
    # Save detailed results
    output = {
        'baseline_commit': '541591727d441d7033a4077d98fbfb373feea787',
        'stats': stats,
        'results': [asdict(r) for r in results]
    }
    
    out_path = Path(__file__).parent / "probe_baseline_results.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\nDetailed results saved to: {out_path}")


if __name__ == "__main__":
    main()