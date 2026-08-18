#!/usr/bin/env python3
"""Evaluate safety and structured evidence selection on non-FAQ questions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from app.config import Settings
from app.pipeline import Pipeline


def main() -> int:
    root = Path(__file__).parent.parent
    cases = json.loads((root / "eval/out_of_faq_reasoning.json").read_text(encoding="utf-8"))["cases"]
    pipeline = Pipeline(settings=Settings(app_mode="mock", retrieval_backend="bm25", llm_backend="mock", tts_backend="mock"))
    original_reason = pipeline.agentic_reasoner.reason
    captured = {}

    def capture(query, chunks):
        result = original_reason(query, chunks)
        captured[query] = {
            "evidence_used": result.evidence_used,
            "key_claims": result.key_claims,
            "excluded_chunks": result.excluded_chunks,
            "source_ids": result.source_ids,
        }
        return result

    pipeline.agentic_reasoner.reason = capture
    session = pipeline.create_session()
    failures = []

    for case in cases:
        result = pipeline.process_text(session, case["query"])
        reasoning = captured.get(case["query"])
        answer_text = result.answer.answer_text.lower() if result.answer else ""
        errors = []
        if result.decision.zone.value != case["expected_zone"]:
            errors.append(f"zone={result.decision.zone.value}")
        if result.decision.action.value != case["expected_action"]:
            errors.append(f"action={result.decision.action.value}")
        if bool(reasoning) != case["reasoning_expected"]:
            errors.append(f"reasoning_present={bool(reasoning)}")
        if reasoning:
            if not reasoning["evidence_used"]:
                errors.append("no_evidence_used")
            if not reasoning["key_claims"]:
                errors.append("no_key_claims")
            allowed = set(reasoning["source_ids"])
            for claim in reasoning["key_claims"]:
                if claim.get("evidence") not in allowed:
                    errors.append("claim_points_to_unselected_source")
        for text in case.get("must_contain", []):
            if text.lower() not in answer_text:
                errors.append(f"missing:{text}")
        status = "PASS" if not errors else "FAIL"
        print(f"{status} {case['id']} | {result.decision.zone.value}/{result.decision.action.value} | reasoning={'Y' if reasoning else 'N'}")
        if reasoning:
            print(f"  used={reasoning['evidence_used']} claims={len(reasoning['key_claims'])} excluded={len(reasoning['excluded_chunks'])}")
        if errors:
            print("  " + "; ".join(errors))
            failures.append(case["id"])

    print(f"\nReasoning checks: {len(cases) - len(failures)}/{len(cases)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
