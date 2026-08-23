# -*- coding: utf-8 -*-
"""Detect the machine and pick the strongest reasoning setup that fits.

Writes recommended settings into .env (only keys not already set) so
non-technical users just run CaiDat.bat once.

Tiers (strongest local reasoning first):
  GPU >= 8GB VRAM  -> Ollama qwen2.5:14b-instruct (or 7b on 6-7GB)
  RAM  >= 16GB     -> Ollama qwen2.5:7b-instruct-q4_K_M on CPU
  RAM  >= 8GB      -> Ollama qwen2.5:3b-instruct
  below / no Ollama-> cloud Gemini (needs key) else mock
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys


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


def _ollama_ready() -> bool:
    return shutil.which("ollama") is not None or _port_open(11434)


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
    }
    info["recommendation"] = recommend(info)
    return info


def recommend(info: dict) -> dict:
    ram = info["ram_gb"]
    vram = info["gpu_vram_gb"]
    ollama = info["ollama"]
    if vram >= 8 and ollama:
        model, note = "qwen2.5:14b-instruct-q4_K_M", "GPU mạnh - suy luận local tốt nhất"
    elif vram >= 6 and ollama:
        model, note = "qwen2.5:7b-instruct-q4_K_M", "GPU vừa - nhanh"
    elif ram >= 16 and ollama:
        model, note = "qwen2.5:7b-instruct-q4_K_M", "CPU nhiều RAM - chậm hơn nhưng đủ dùng"
    elif ram >= 8 and ollama:
        model, note = "qwen2.5:3b-instruct-q4_K_M", "Máy yếu - bản gọn"
    elif ram >= 8:
        model, note = "", "Chưa có Ollama - khuyến nghị cài để chạy AI trong máy"
    else:
        model, note = "", "Máy cấu hình thấp - dùng chế độ cloud (cần API key)"
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


def write_env(reco: dict, env_path: str = ".env.local") -> str:
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
        model=reco["ollama_model"] or "qwen2.5:7b-instruct-q4_K_M",
    )
    with open(env_path, "a", encoding="utf-8") as fh:
        fh.write("\n" + content)
    return env_path


if __name__ == "__main__":
    import json

    print(json.dumps(detect(), ensure_ascii=False, indent=2))
