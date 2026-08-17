"""Run all evaluations (R1-R4) with demo fixtures and write the report.

All results are watermarked "SYNTHETIC DEMO - NOT PILOT RESULTS".

Usage:
    python -m eval.run_all --input-wer data/eval/wer_dev.jsonl (optional)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.retrieval.bm25_retriever import BM25Retriever
from app.safety.policy import Policy
from app.safety.router import SafetyRouter
from eval import latency, retrieval, routing, wer
from eval.common import WATERMARK

RESULTS = Path("results")


def build_wer_fixture() -> Path:
    """Create an in-memory WER fixture if data/eval/wer_dev.jsonl is absent."""
    fixture = Path("data/eval/wer_dev.jsonl")
    if not fixture.exists():
        fixture.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            {
                "case_id": 1,
                "accent_group": "northern",
                "reference": "thủ tục cấp giấy xác nhận hộ khẩu",
                "hypothesis": "thủ tục cấp giấy xác nhận hộ khẩu",
            },
            {
                "case_id": 2,
                "accent_group": "northern",
                "reference": "đăng ký khai sinh cho con tại xã",
                "hypothesis": "đăng ký khai sinh cho con tại xa",
            },
            {
                "case_id": 3,
                "accent_group": "southern",
                "reference": "xác nhận tình trạng hôn nhân mất bao lâu",
                "hypothesis": "xác nhận tình trạng hôn nhân mất bao lau",
            },
            {
                "case_id": 4,
                "accent_group": "southern",
                "reference": "đăng ký tạm trú ở xã bình minh",
                "hypothesis": "đăng ký tạm tru ở xã bình minh",
            },
            {
                "case_id": 5,
                "accent_group": "standard",
                "reference": "hỗ trợ khó khăn đột xuất cần hồ sơ gì",
                "hypothesis": "hỗ trợ khó khăn đột suất cần hồ sơ gì",
            },
            {
                "case_id": 6,
                "accent_group": "standard",
                "reference": "lệ phí xác nhận hộ khẩu là bao nhiêu",
                "hypothesis": "lệ phí xác nhận hộ khẩu là bao nhiêu",
            },
        ]
        fixture.write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
            encoding="utf-8",
        )
    return fixture


def build_latency_fixture() -> Path:
    fixture = Path("data/eval/latency_dev.jsonl")
    if not fixture.exists():
        fixture.parent.mkdir(parents=True, exist_ok=True)
        import random

        rng = random.Random(42)
        lines = []
        for i in range(12):
            hold = i % 2 == 0
            lines.append(
                {
                    "case_id": i,
                    "hold_message": hold,
                    "asr_ms": round(rng.uniform(1500, 4200), 1),
                    "retrieval_ms": round(rng.uniform(20, 90), 1),
                    "llm_ms": round(rng.uniform(800, 2600), 1),
                    "tts_ms": round(rng.uniform(300, 1500), 1),
                    "total_ms": round(rng.uniform(3200, 7800), 1),
                }
            )
        fixture.write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
            encoding="utf-8",
        )
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R1-R4 demo evaluations")
    parser.add_argument("--input-wer", type=Path, default=None)
    parser.add_argument("--results-dir", type=Path, default=RESULTS)
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    chunks_file = Path("data/chunks/demo_chunks.jsonl")
    if not chunks_file.exists():
        from app.retrieval.document_loader import DocumentLoader

        DocumentLoader().ingest()

    # R1
    wer_input = args.input_wer or build_wer_fixture()
    wer_rows, wer_summary = wer.evaluate_wer(wer.load_jsonl(wer_input))
    wer.save_csv(results_dir / "wer_results.csv", wer_rows)
    wer.save_json(results_dir / "wer_summary.json", wer_summary)

    # R2
    retriever = BM25Retriever.from_jsonl(chunks_file)
    ret_rows, ret_summary = retrieval.evaluate_retrieval(
        retrieval.load_jsonl("data/eval/retrieval_dev.jsonl"), retriever
    )
    retrieval.save_csv(results_dir / "retrieval_results.csv", ret_rows)
    retrieval.save_json(results_dir / "retrieval_summary.json", ret_summary)

    # R3
    router = SafetyRouter(settings=Settings(), policy=Policy())
    rout_rows, rout_summary = routing.evaluate_routing(
        routing.load_jsonl("data/eval/routing_test.jsonl"), router, retriever
    )
    routing.save_csv(results_dir / "routing_results.csv", rout_rows)
    routing.save_json(results_dir / "routing_summary.json", rout_summary)

    # R4
    lat_input = build_latency_fixture()
    lat_rows, lat_summary = latency.evaluate_latency(latency.load_jsonl(lat_input))
    latency.save_csv(results_dir / "latency_results.csv", lat_rows)
    latency.save_json(results_dir / "latency_summary.json", lat_summary)

    report = _build_report(wer_summary, ret_summary, rout_summary, lat_summary)
    (results_dir / "evaluation_report.md").write_text(report, encoding="utf-8")
    print(f"[EVAL] wrote results to {results_dir}/")
    print(
        f"  WER={wer_summary['wer']:.4f} | ret top-1={ret_summary['top1_accuracy']:.4f} "
        f"| zone={rout_summary['zone_accuracy']:.4f} "
        f"| total p50={lat_summary['stages']['total_ms']['p50_ms']}ms"
    )
    return 0


def _build_report(*summaries: dict) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Evaluation report (R1-R4)",
        "",
        f"> **{WATERMARK}**",
        f"> Generated: {now}",
        "",
        "## R1 - WER",
        f"- Cases: {summaries[0]['cases']}, WER: **{summaries[0]['wer']:.4f}**",
        "",
        "## R2 - Retrieval",
        f"- Cases: {summaries[1]['cases']}, top-1: **{summaries[1]['top1_accuracy']:.4f}**, "
        f"MRR: **{summaries[1]['mrr']:.4f}**",
        "",
        "## R3 - Routing",
        f"- Cases: {summaries[2]['cases']}, zone: **{summaries[2]['zone_accuracy']:.4f}**, "
        f"action: **{summaries[2]['action_accuracy']:.4f}**",
        f"- RED false-safe rate: {summaries[2]['red_false_safe_rate']}",
        f"- Safe false-refusal rate: {summaries[2]['safe_false_refusal_rate']}",
        "",
        "## R4 - Latency (synthetic fixture)",
    ]
    total = summaries[3]["stages"]["total_ms"]
    lines.append(
        f"- total: mean={total['mean_ms']}ms p50={total['p50_ms']}ms "
        f"p90={total['p90_ms']}ms max={total['max_ms']}ms"
    )
    for stage in ("asr_ms", "retrieval_ms", "llm_ms", "tts_ms"):
        s = summaries[3]["stages"][stage]
        if s["n"]:
            lines.append(f"- {stage}: mean={s['mean_ms']}ms p50={s['p50_ms']}ms")
    lines.append("")
    lines.append("## Reproducibility")
    lines.append("```")
    lines.append("python -m eval.run_all")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
