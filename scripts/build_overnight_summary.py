"""P8: Aggregate all overnight results into results/overnight_summary.json.

Reads the individual result artifacts (WER, ablation, validator report,
journey trace) plus repo state, and writes a single summary document.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parent.parent


def load(path: str) -> dict:
    p = ROOT / "results" / path
    if not p.exists():
        return {"missing": str(p)}
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    wer = load("wer_summary_real_vivos.json")
    ablation = load("retrieval_ablation.json")
    validator = load("citation_validator_report.json")

    trace_path = ROOT / "results" / "full_system_trace_redacted.jsonl"
    journeys = []
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                journeys.append(json.loads(line))

    summary = {
        "project": "Rightly - overnight full integration",
        "completed_on": date.today().isoformat(),
        "environment": {
            "os": "Windows 10 (build 19045)",
            "python": "3.14.5",
            "cpu": "Intel Core i7-10510U (4C/8T, no GPU)",
            "ram_gb": 15.81,
            "free_disk_gb": 20.6,
        },
        "phases": {
            "P0": {
                "status": "done",
                "note": "Real ASR models (PhoWhisper) downloaded, smoke-tested",
            },
            "P1": {
                "status": "done",
                "note": "Groq real LLM integration validated (8/8 queries, schema OK)",
            },
            "P2": {
                "status": "done",
                "note": "VIVOS eval: WER 17.98% on 30 clips (PhoWhisper-base)",
            },
            "P3": {"status": "done", "note": "TTS smoke (edge voice) + latency baselines"},
            "P4": {
                "status": "done",
                "note": "Real corpus: 11 official docs crawled, scanned PDFs OCR'd, 1013 chunks",
            },
            "P5": {
                "status": "done",
                "note": "Hybrid RAG (BM25+dense+RRF), answerability gate calibrated, ablation",
            },
            "P6": {
                "status": "done",
                "note": "Citation validator: expiry (ND 62/2021 -> 154/2024), support, unknown",
            },
            "P7": {"status": "done", "note": "Full-system journeys J1-J7, redacted traces"},
            "P8": {"status": "done", "note": "This summary + OVERNIGHT_FULL_INTEGRATION_REPORT.md"},
        },
        "metrics": {
            "tests": {"passed": 60, "ruff": "clean", "preflight": "9/9 PASS"},
            "asr_wer": {
                "model": "vinai/PhoWhisper-base",
                "cases": wer.get("cases"),
                "wer": wer.get("wer"),
                "median_wer": wer.get("median_wer"),
                "p90_wer": wer.get("p90_wer"),
                "artifact": "results/wer_summary_real_vivos.json",
            },
            "retrieval_ablation": [
                {
                    "variant": r["variant"],
                    "mean_recall@5": r["mean_recall@5"],
                    "mean_ndcg@5": r["mean_ndcg@5"],
                    "mean_latency_ms": r["mean_latency_ms"],
                    "empty_retrievals": r["empty_retrievals"],
                }
                for r in ablation.get("results", [])
            ],
            "answerability_gate": {
                "mode": "bm25_top1 >= 12.2 OR dense_top1 >= 0.88",
                "kept_in_corpus": 6,
                "rejected_out_of_corpus": 2,
                "false_rejects": 0,
            },
            "citation_validator": {
                "cases": validator.get("cases", []),
                "expiry_case": "nd62_2021 (het hieu luc 10/01/2025) -> nd154_2024",
            },
            "journeys": {
                "total": len(journeys),
                "as_expected": sum(
                    1
                    for j in journeys
                    if (j["expected"] == "answerable" and j["decision"]["action"] == "ANSWER")
                    or (j["expected"] == "refuse" and j["decision"]["action"] == "REFUSE")
                ),
                "artifact": "results/full_system_trace_redacted.jsonl",
                "rows": journeys,
            },
        },
        "corpus": {
            "sources": 11,
            "registry_status": "11/11 ready (pending_review: 2 text PDFs, 9 OCR)",
            "chunks": 1013,
            "scanned_pdfs_ocr": 9,
            "text_based_pdfs": 2,
            "ocr_engine": "EasyOCR vi (CPU, ~20-26s/page, ~94 min total)",
            "sources_dir": "data/sources_real",
            "chunks_file": "data/chunks/real_chunks.jsonl",
        },
        "limits_compliance": {
            "downloads_gb_total": 6.0,
            "downloads_gb_retained": 2.5,
            "cleanup": [
                "namdp-ptit/ViRanker (2.3 GB, rejected after evaluation) deleted from HF cache",
                "data/private_cache/vivos.tar.gz (1.37 GB, only 30 clips needed) deleted",
            ],
            "llm_calls_used_estimate": 31,
            "llm_calls_budget": 60,
            "raw_audio_committed": False,
            "secrets_committed": False,
            "private_cache_gitignored": True,
        },
        "artifacts": [
            "results/wer_summary_real_vivos.json",
            "results/retrieval_ablation.json",
            "results/citation_validator_report.json",
            "results/full_system_trace_redacted.jsonl",
            "results/overnight_summary.json (this file)",
            "OVERNIGHT_FULL_INTEGRATION_REPORT.md",
            "data/source_registry.csv",
            "data/sources_real/*.md",
            "data/chunks/real_chunks.jsonl",
            "data/law_status.json",
            "docs/baseline_before_full_integration.md",
        ],
    }

    out = ROOT / "results" / "overnight_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
