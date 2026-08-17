"""Automatic, privacy-safe evidence capture for local demo runs."""

from __future__ import annotations

import hashlib
import json
import platform
import time
from pathlib import Path
from typing import Any


def _hardware() -> dict[str, Any]:
    info: dict[str, Any] = {
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
    }
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            info["cuda_device"] = torch.cuda.get_device_name(0)
    except Exception as exc:  # optional dependency
        info["torch"] = "unavailable"
        info["torch_error"] = type(exc).__name__
    try:
        import openvino as ov

        info["openvino"] = ov.__version__
        info["openvino_devices"] = list(ov.Core().available_devices)
    except Exception:
        info["openvino"] = "unavailable"
        info["openvino_devices"] = []
    return info


def _write_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_local_evidence(settings, llm) -> dict[str, Any]:
    """Record local runtime metadata and run a one-time model smoke benchmark.

    The benchmark contains fixed non-user prompts and is explicitly marked as
    benchmark data. It never falls back to cloud and never records responses.
    """
    results = settings.resolved_results_dir()
    hardware = _hardware()
    identity = json.dumps(
        {"model": getattr(llm, "model", "unknown"), "base_url": getattr(llm, "base_url", ""), "hardware": hardware},
        sort_keys=True,
    ).encode()
    key = hashlib.sha256(identity).hexdigest()[:16]
    marker = results / f"local_benchmark_{key}.json"
    manifest = {
        "record_type": "local_runtime_manifest",
        "mode": "local",
        "model": getattr(llm, "model", "unknown"),
        "base_url": getattr(llm, "base_url", ""),
        "hardware": hardware,
        "offline_claim": "not_verified",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_jsonl(results / "local_runtime_sessions.jsonl", manifest)
    if marker.exists():
        return json.loads(marker.read_text(encoding="utf-8"))

    prompts = [
        "Nêu một câu ngắn xác nhận đang chạy local.",
        "Trả lời một câu ngắn: bước benchmark thứ hai đã hoàn tất chưa?",
        "Trả lời một câu ngắn: local runtime có phản hồi không?",
    ]
    rows = []
    for prompt in prompts:
        started = time.perf_counter()
        error = ""
        try:
            # Direct local call: no retrieved context, no participant data.
            llm._generate(
                llm._get_client(),
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format=None,
            )
        except Exception as exc:  # retain evidence of failed readiness
            error = type(exc).__name__
        rows.append({"latency_ms": round((time.perf_counter() - started) * 1000, 1), "error": error})
    benchmark = {
        **manifest,
        "record_type": "local_benchmark",
        "benchmark_prompts": len(prompts),
        "runs": rows,
        "mean_latency_ms": round(sum(r["latency_ms"] for r in rows) / len(rows), 1),
        "passed": all(not r["error"] for r in rows),
        "synthetic": True,
    }
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return benchmark
