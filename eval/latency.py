"""R4 - Latency evaluation: P50/P90/max/mean across pipeline stages.

Input JSONL: records with asr_ms, retrieval_ms, llm_ms, tts_ms, total_ms
(any subset allowed; missing keys are treated as 0 and reported as absent).
Optional `hold_message` boolean column for hold-on/hold-off comparison.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.common import load_jsonl, median, percentile, save_csv, save_json, watermark_summary

PACKAGE_VERSION = "4.0.0"

_STAGES = ["asr_ms", "retrieval_ms", "llm_ms", "tts_ms", "total_ms"]


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean_ms": 0.0, "p50_ms": 0.0, "p90_ms": 0.0, "max_ms": 0.0}
    return {
        "n": len(values),
        "mean_ms": round(sum(values) / len(values), 1),
        "p50_ms": round(median(values), 1),
        "p90_ms": round(percentile(values, 90), 1),
        "max_ms": round(max(values), 1),
    }


def evaluate_latency(records: list[dict]) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    for idx, rec in enumerate(records):
        row = {"case_id": rec.get("case_id", idx)}
        if "hold_message" in rec:
            row["hold_message"] = rec["hold_message"]
        for stage in _STAGES:
            val = rec.get(stage)
            row[stage] = round(float(val), 1) if val is not None else None
        rows.append(row)

    overall: dict[str, dict] = {}
    for stage in _STAGES:
        values = [r[stage] for r in rows if r[stage] is not None]
        overall[stage] = _stats(values)

    by_hold: dict[str, dict[str, dict]] = {}
    if any("hold_message" in r for r in rows):
        by_hold = {"true": {}, "false": {}}
        for key in ("true", "false"):
            subset = [r for r in rows if str(r.get("hold_message", "")).lower() == key]
            for stage in _STAGES:
                values = [r[stage] for r in subset if r[stage] is not None]
                by_hold[key][stage] = _stats(values)

    summary = watermark_summary(
        {
            "cases": len(rows),
            "stages": overall,
            "hold_message_comparison": by_hold,
        },
        "R4_LATENCY",
        PACKAGE_VERSION,
    )
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="R4 latency evaluation")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, default=Path("results/latency_results.csv"))
    parser.add_argument("--output-json", type=Path, default=Path("results/latency_summary.json"))
    args = parser.parse_args()
    rows, summary = evaluate_latency(load_jsonl(args.input))
    save_csv(args.output_csv, rows)
    save_json(args.output_json, summary)
    total = summary["stages"]["total_ms"]
    print(f"total p50={total['p50_ms']}ms p90={total['p90_ms']}ms max={total['max_ms']}ms")


if __name__ == "__main__":
    main()
