"""Log pilot metrics (WER/MOS/CSAT) — P uses during real pilots (13/08, 18/08).

Usage:
    python scripts/log_pilot_metrics.py --audio <wav> --ref "câu đúng cần nói" \
        --task-id ho-khau --accent bac
Then answer interactive prompts: task success (co/khong) + CSAT 1-5.

Appends one record per run to data/eval/pilot_metrics.jsonl. Records are
anonymous (no names); raw audio stays on the pilot device (not uploaded).
Aggregation for Technical Rigor (14/08): median WER, task success rate, CSAT.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parent.parent.as_posix())

from eval.wer import evaluate_wer  # noqa: E402

METRICS_FILE = Path("data") / "eval" / "pilot_metrics.jsonl"
EVIDENCE_MD = Path("results") / "pilot_evidence_pack.md"
EVIDENCE_JSON = Path("results") / "pilot_evidence_pack.json"


def _hardware() -> dict[str, str]:
    info = {"os": platform.platform(), "machine": platform.machine(), "python": platform.python_version()}
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda_available"] = str(bool(torch.cuda.is_available()))
        if torch.cuda.is_available():
            info["cuda_device"] = torch.cuda.get_device_name(0)
    except Exception:
        info["torch"] = "unavailable"
    return info


def _ask(prompt: str, choices: dict[str, str], default: str = "") -> str:
    label = "/".join(f"{k}={v}" for k, v in choices.items())
    while True:
        raw = (
            input(f"{prompt} [{label}]{' [default: ' + default + ']' if default else ''}: ")
            .strip()
            .lower()
        )
        if not raw and default:
            return default
        if raw in choices:
            return raw
        print(f"  -> chấp nhận: {', '.join(choices)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Pilot WER/CSAT logging (anonymous)")
    ap.add_argument("--export", action="store_true", help="export aggregate evidence pack")
    ap.add_argument("--audio", required=False, help="Path to pilot audio (wav)")
    ap.add_argument("--ref", required=False, help="Reference transcript the user should say")
    ap.add_argument("--task-id", required=False, help="Pilot task id (e.g. ho-khau)")
    ap.add_argument("--accent", default="", help="accent_group: bac/trung/nam (optional)")
    ap.add_argument("--participant-id", required=False, help="anonymous id, e.g. P01; never use a name")
    ap.add_argument("--mode", default="local", choices=["local", "cloud", "mock"])
    ap.add_argument("--device", default="", help="human-readable device/NPU name")
    ap.add_argument("--consent-audio", action="store_true")
    ap.add_argument("--consent-transcript", action="store_true")
    ap.add_argument("--consent-video", action="store_true")
    ap.add_argument("--keep-text", action="store_true", help="store transcript/reference; off by default")
    args = ap.parse_args()

    if args.export:
        return export_evidence()
    if not args.audio or not args.ref or not args.task_id:
        print("ERROR: --audio, --ref and --task-id are required when logging a session")
        return 2
    if not args.participant_id or not args.participant_id.startswith("P"):
        print("ERROR: use an anonymous participant id such as P01 (no names/phone numbers)")
        return 2
    if not args.consent_audio and not args.consent_transcript:
        print("ERROR: record only after consent for audio or transcript (--consent-audio/--consent-transcript)")
        return 2

    audio = Path(args.audio)
    if not audio.exists():
        print(f"ERROR: audio not found: {audio}")
        return 2

    from app.asr.phowhisper_asr import PhoWhisperASR

    print("Transcribing...")
    t0 = time.perf_counter()
    result = PhoWhisperASR().transcribe(audio)
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    transcript = result.transcript.strip()
    print(f"ASR: {transcript!r}")
    print(f"REF: {args.ref!r}")

    (wer, subs, ins, dels), stats = evaluate_wer(
        [{"reference": args.ref, "hypothesis": transcript}]
    )
    print(f"WER = {wer * 100:.1f}%  (sub={subs} ins={ins} del={dels}, latency={latency_ms}ms)")

    success = _ask("Task hoàn thành đúng?", {"co": "yes", "khong": "no"})
    csat = _ask(
        "Độ hài lòng người dùng 1-5?",
        {"1": "rất tệ", "2": "tệ", "3": "tạm", "4": "tốt", "5": "rất tốt"},
    )
    comment = input("Ghi chú (tùy chọn, không ghi tên người): ").strip()

    record = {
        "participant_id": args.participant_id,
        "task_id": args.task_id,
        "accent_group": args.accent,
        "wer": round(wer, 4),
        "latency_ms": latency_ms,
        "task_success": success == "co",
        "csat": int(csat),
        "mos_subjective": int(csat),
        "comment": comment[:500],
        "mode": args.mode,
        "device": args.device,
        "hardware": _hardware(),
        "consent": {
            "audio": args.consent_audio,
            "transcript": args.consent_transcript,
            "video": args.consent_video,
        },
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if args.keep_text and args.consent_transcript:
        record["transcript"] = transcript
        record["reference"] = args.ref
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with METRICS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Saved -> {METRICS_FILE}")
    return 0


def export_evidence() -> int:
    rows = []
    if METRICS_FILE.exists():
        with METRICS_FILE.open(encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    legacy_count = sum(1 for r in rows if not r.get("participant_id"))
    rows = [r for r in rows if r.get("participant_id")]
    if not rows:
        print(f"ERROR: no records in {METRICS_FILE}")
        return 2
    participants = sorted({r.get("participant_id", "unknown") for r in rows})
    tasks = sorted({r.get("task_id", "unknown") for r in rows})
    success = sum(bool(r.get("task_success")) for r in rows)
    csat = [int(r["csat"]) for r in rows if r.get("csat") is not None]
    wers = [float(r["wer"]) for r in rows if r.get("wer") is not None]
    latencies = [float(r["latency_ms"]) for r in rows if r.get("latency_ms") is not None]
    summary = {
        "record_count": len(rows),
        "participant_count": len(participants),
        "participants": participants,
        "tasks": tasks,
        "task_success_rate": round(success / len(rows), 4),
        "mean_csat": round(sum(csat) / len(csat), 2) if csat else None,
        "mean_wer": round(sum(wers) / len(wers), 4) if wers else None,
        "mean_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "modes": sorted({r.get("mode", "unknown") for r in rows}),
        "devices": sorted({r.get("device", "unknown") for r in rows}),
        "consent_note": "Aggregate only; raw audio and transcript are not included by default.",
        "excluded_legacy_records": legacy_count,
    }
    EVIDENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Pilot Evidence Pack",
        "",
        "> Generated from anonymous local pilot logs. Verify consent and claims before submission.",
        "> This pack contains aggregate metrics only; it is not synthetic data.",
        "",
        f"- Sessions: {summary['record_count']}",
        f"- Participants: {summary['participant_count']}",
        f"- Tasks: {', '.join(tasks)}",
        f"- Task success rate: {summary['task_success_rate']:.1%}",
        f"- Mean satisfaction (1-5): {summary['mean_csat']}",
        f"- Mean WER: {summary['mean_wer']:.1%}" if summary["mean_wer"] is not None else "- Mean WER: n/a",
        f"- Mean latency: {summary['mean_latency_ms']} ms",
        f"- Mode(s): {', '.join(summary['modes'])}",
        f"- Device(s): {', '.join(summary['devices'])}",
        f"- Legacy records excluded: {legacy_count}",
        "",
        "## Human Review Required",
        "",
        "- Confirm participant consent scope for audio, transcript and video.",
        "- Confirm device/NPU and offline status from the corresponding run log/video.",
        "- Do not claim adoption, deployment scale or causality from this summary alone.",
    ]
    EVIDENCE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved -> {EVIDENCE_MD}")
    print(f"Saved -> {EVIDENCE_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
