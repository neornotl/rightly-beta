#!/usr/bin/env python3
"""Content-level regression checks for questions outside the curated FAQ."""

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
    cases = json.loads((root / "eval/content_checks.json").read_text(encoding="utf-8"))["cases"]
    pipeline = Pipeline(settings=Settings(app_mode="mock", retrieval_backend="bm25", llm_backend="mock", tts_backend="mock"))
    session = pipeline.create_session()
    failures = []
    for case in cases:
        result = pipeline.process_text(session, case["query"])
        answer = result.answer.answer_text.lower() if result.answer else ""
        sources = set(result.answer.source_ids if result.answer else [])
        errors = []
        if case.get("expected_zone") and result.decision.zone.value != case["expected_zone"]:
            errors.append(f"zone={result.decision.zone.value}")
        if case.get("expected_action") and result.decision.action.value != case["expected_action"]:
            errors.append(f"action={result.decision.action.value}")
        errors += [f"missing:{x}" for x in case.get("must_contain", []) if x.lower() not in answer]
        errors += [f"forbidden:{x}" for x in case.get("must_not_contain", []) if x.lower() in answer]
        if case.get("must_source") and not sources.intersection(case["must_source"]):
            errors.append(f"source_not_found:{case['must_source']}")
        status = "PASS" if not errors else "FAIL"
        print(f"{status} {case['id']} | {result.decision.zone.value}/{result.decision.action.value} | sources={sorted(sources)}")
        if errors:
            print("  " + "; ".join(errors))
            failures.append(case["id"])
    print(f"\nContent checks: {len(cases) - len(failures)}/{len(cases)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
