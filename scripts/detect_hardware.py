# -*- coding: utf-8 -*-
"""Detect the machine and pick a balanced reasoning setup that stays fast.

Writes recommended settings into .env (only keys not already set) so
non-technical users just run CaiDat.bat once.

Tiers (balanced by default; never choose the largest model automatically):
  GPU >= 8GB VRAM  -> Ollama qwen2.5:7b-instruct-q4_K_M
  RAM >= 24GB and 12+ cores -> Ollama qwen2.5:7b-instruct-q4_K_M on CPU
  RAM  >= 8GB      -> Ollama qwen2.5:3b-instruct-q4_K_M on CPU
  below / no Ollama-> cloud Gemini (needs key) else mock
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

try:  # Windows terminals may still use cp1252; hardware notes are UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _win_ram_gb() -> float:
    try:
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
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullTotalPhys / (1024 ** 3)
    except Exception:
        return 0.0


def _nvidia_vram_gb() -> float:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        mib = [float(x.strip()) for x in out.stdout.splitlines() if x.strip().isdigit()]
        return max(mib) / 1024 if mib else 0.0
    except Exception:
        return 0.0


def _ollama_path() -> str | None:
    """Find Ollama even when its installer has not refreshed this process PATH."""
    found = shutil.which("ollama")
    if found:
        return found
    candidates: list[str] = []
    for env_name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_name)
        if not base:
            continue
        root = os.path.abspath(base)
        candidates.extend(
            os.path.join(root, rel)
            for rel in (
                "Programs\\Ollama\\ollama.exe",
                "Ollama\\ollama.exe",
                "Ollama\\bin\\ollama.exe",
            )
        )
    return next((path for path in candidates if os.path.isfile(path)), None)


def _ollama_ready() -> bool:
    return _ollama_path() is not None or _port_open(11434)


def _port_open(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def detect() -> dict:
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "cpu_cores": os.cpu_count() or 0,
        "ram_gb": round(_win_ram_gb() if sys.platform == "win32" else 0, 1),
        "gpu_vram_gb": round(_nvidia_vram_gb(), 1),
        "ollama": _ollama_ready(),
        "ollama_path": _ollama_path(),
    }
    info["recommendation"] = recommend(info)
    return info


def recommend(info: dict) -> dict:
    ram = info["ram_gb"]
    vram = info["gpu_vram_gb"]
    cores = info.get("cpu_cores", 0)
    # Choose the model from hardware even before Ollama is installed; the
    # one-time installer will install the selected runtime immediately after.
    # 7B is reserved for machines where it remains responsive. A 7B model on
    # a typical 16GB CPU-only laptop can take 30-60s per answer; 3B is the
    # balanced default and is still grounded by Rightly's legal retrieval.
    if vram >= 8:
        model, note = "qwen2.5:7b-instruct-q4_K_M", "GPU >= 8 GB - 7B chạy nhanh, chất lượng cao"
    elif ram >= 24 and cores >= 12:
        model, note = "qwen2.5:7b-instruct-q4_K_M", "CPU/RAM mạnh - 7B vẫn đủ nhanh"
    elif ram >= 8:
        model, note = "qwen2.5:3b-instruct-q4_K_M", "Cấu hình phổ biến - 3B cân bằng tốc độ và độ thông minh"
    else:
        model, note = "", "May cau hinh thap - khong dat yeu cau offline 8GB RAM"
    return {
        "llm_backend": "local" if model else ("gemini" if ram >= 4 else "mock"),
        "ollama_model": model,
        "note": note,
    }


ENV_TEMPLATE = """# --- do CaiDat-Rightly sinh ra {date} ---
APP_MODE=local
ASR_BACKEND=whisper
RETRIEVAL_BACKEND=bm25
TTS_BACKEND=mock
LLM_BACKEND={llm_backend}
{llm_block}
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL={model}
"""


def write_env(reco: dict, env_path: str = ".rightly-hardware.env") -> str:
    llm_block = ""
    if reco["llm_backend"] == "local":
        pass  # Ollama needs no key
    else:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        llm_block = f"GEMINI_API_KEY={gemini_key}\nGEMINI_THINKING_BUDGET=512\n" if gemini_key else "# Thêm GEMINI_API_KEY vào file này để dùng AI cloud\n"
    content = ENV_TEMPLATE.format(
        date=__import__("datetime").date.today().isoformat(),
        llm_backend=reco["llm_backend"],
        llm_block=llm_block,
        model=reco["ollama_model"] or "qwen2.5:3b-instruct-q4_K_M",
    )
    # This is a generated recommendation file, so replace it on each run.
    # Appending would leave duplicate keys and make the selected model depend
    # on which dotenv parser happened to read the file last.
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return env_path


if __name__ == "__main__":
    import json

    info = detect()
    print(json.dumps(info, ensure_ascii=False, indent=2))
    print(f"Wrote hardware recommendation to {write_env(info['recommendation'])}")
