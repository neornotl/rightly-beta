"""Detect local hardware and recommend the best model config for Rightly.

Run standalone:
    python scripts/detect_hardware.py

Or have start.bat call it to auto-fill .env on first install:
    python scripts/detect_hardware.py --write .env

Reads (no third-party deps required; all stdlib + optional psutil/wmi):
  - Total RAM (GB)
  - CPU core count
  - GPU VRAM (nvidia-smi -> MB; else 0 = CPU-only)
  - Free disk space (GB)

Picks a tier that keeps the model running in memory with headroom and
writes OLLAMA_MODEL / WHISPER_MODEL / WHISPER_DEVICE / ASR_BACKEND /
LLM_BACKEND / TTS_BACKEND accordingly.

Tiers (RAM is the binding constraint on CPU-only laptops):
  <6 GB  -> LLM: none (mock) + whisper tiny      (survival)
  6-11   -> LLM: qwen2.5:3b-instruct-q4_k_m + whisper base
  11-15  -> LLM: qwen2.5:7b-instruct-q4_k_m + whisper small
  >=16   -> LLM: qwen3:8b + whisper small/medium

GPU VRAM overrides: >=6GB VRAM allows the same models on CUDA.
Disk guard: refuse to write a config that needs more model cache than
free space.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def detect_cpu_cores() -> int:
    return os.cpu_count() or 4


def detect_total_ram_gb() -> float:
    try:
        import psutil  # type: ignore
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        pass
    try:
        # Windows stdlib fallback via ctypes
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return round(stat.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        pass
    return 8.0


def detect_gpu_vram_mb() -> int:
    """GPU VRAM in MB; 0 means no usable GPU detected (CPU-only)."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return int(re.sub(r"\D", "", out.stdout.splitlines()[0]) or 0)
    except Exception:
        pass
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            return int(torch.cuda.get_device_properties(0).total_memory / (1024 ** 2))
    except Exception:
        pass
    return 0


def detect_free_disk_gb() -> float:
    try:
        total, used, free = shutil.disk_usage(ROOT)
        return round(free / (1024 ** 3), 1)
    except Exception:
        return 0.0


def recommend(ram_gb: float, cores: int, vram_mb: int, free_gb: float) -> dict:
    vram_gb = vram_mb / 1024
    gpu = vram_gb >= 6.0
    device = "cuda" if gpu else "cpu"

    # LLM tier. On CPU-only machines bigger models are unusably slow, so the
    # tier keeps 3b until RAM is ample (>=16GB) unless a real GPU exists.
    if ram_gb < 6:
        llm_model = "mock"          # too weak for a local LLM
        llm_backend = "mock"
    elif ram_gb < 11:
        llm_model = "qwen2.5:3b-instruct-q4_k_m"
        llm_backend = "local"
    elif gpu:
        llm_model = "qwen2.5:7b-instruct-q4_k_m"
        llm_backend = "local"
    elif ram_gb < 16:
        llm_model = "qwen2.5:3b-instruct-q4_k_m"   # CPU-only: keep it fast
        llm_backend = "local"
    elif ram_gb < 20:
        llm_model = "qwen2.5:7b-instruct-q4_k_m"   # CPU-only but lots of RAM
        llm_backend = "local"
    else:
        llm_model = "qwen3:8b"
        llm_backend = "local"

    # ASR tier (whisper is the offline default)
    if ram_gb < 6:
        whisper_model = "tiny"
    elif ram_gb < 11:
        whisper_model = "base"
    elif ram_gb < 16:
        whisper_model = "small"
    else:
        whisper_model = "small"     # medium too slow on CPU-only

    # Disk guard: model caches need a few GB
    if free_gb > 0 and free_gb < 4 and llm_backend == "local":
        llm_backend = "mock"
        llm_model = "mock"

    return {
        "ram_gb": ram_gb,
        "cpu_cores": cores,
        "gpu_vram_mb": vram_mb,
        "free_disk_gb": free_gb,
        "gpu_capable": gpu,
        "llm_backend": llm_backend,
        "llm_model": llm_model,
        "whisper_model": whisper_model,
        "whisper_device": device,
        "asr_backend": "whisper" if ram_gb >= 6 else "mock",
        "tts_backend": "edge" if ram_gb >= 6 else "mock",
        "explanation": (
            f"{ram_gb:.1f}GB RAM / {cores} cores / "
            f"{'GPU '+str(vram_mb)+'MB' if vram_mb else 'no GPU'} / "
            f"{free_gb:.1f}GB free disk"
        ),
    }


def _write_env(path: Path, rec: dict) -> None:
    """Update/create a .env with the recommended values (preserve the rest)."""
    replacements = {
        "LLM_BACKEND": rec["llm_backend"],
        "OLLAMA_MODEL": rec["llm_model"],
        "WHISPER_MODEL": rec["whisper_model"],
        "WHISPER_DEVICE": rec["whisper_device"],
        "ASR_BACKEND": rec["asr_backend"],
        "TTS_BACKEND": rec["tts_backend"],
    }
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    updated = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in replacements:
                out.append(f"{key}={replacements[key]}")
                updated.add(key)
                continue
        out.append(line)
    for key, val in replacements.items():
        if key not in updated:
            out.append(f"{key}={val}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rightly hardware auto-detect")
    parser.add_argument(
        "--write", metavar="PATH", default=None,
        help="Write recommended values into a .env file (default: no write)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    rec = recommend(
        ram_gb=detect_total_ram_gb(),
        cores=detect_cpu_cores(),
        vram_mb=detect_gpu_vram_mb(),
        free_gb=detect_free_disk_gb(),
    )

    if args.json:
        import json
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    else:
        print("=== Rightly hardware detection ===")
        print(f"  {rec['explanation']}")
        print(f"  -> LLM backend: {rec['llm_backend']} ({rec['llm_model']})")
        print(f"  -> ASR backend: {rec['asr_backend']} (whisper {rec['whisper_model']}, {rec['whisper_device']})")
        print(f"  -> TTS backend: {rec['tts_backend']}")

    if args.write:
        target = Path(args.write)
        _write_env(target, rec)
        print(f"\nWrote recommended values to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())