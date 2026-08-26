"""Fail-closed readiness check for the installed offline stack."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

try:  # Windows installer consoles may default to cp1252.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A local model on a CPU-only machine can legitimately need a while for the
# full local pipeline (router + retrieval + grounded answer). The old 120s
# smoke-test limit treated that slow-but-valid path as an installation error.
PREFLIGHT_CHAT_TIMEOUT_S = max(
    120, int(os.environ.get("RIGHTLY_PREFLIGHT_CHAT_TIMEOUT", "300"))
)


def _asset_verification_note() -> tuple[bool, str]:
    """Keep readiness and cryptographic asset verification distinct."""
    try:
        manifest = json.loads((ROOT / "scripts" / "asset_manifest.json").read_text(encoding="utf-8"))
        assets = manifest.get("assets", {})
        hashes = [entry.get("sha256", "") for entry in assets.values() if isinstance(entry, dict)]
        verified = any(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) for value in hashes)
        if verified:
            return True, f"Asset checksum verification configured for {len(hashes)} manifest entry/entries."
    except (OSError, ValueError, TypeError):
        pass
    return False, "WARNING: no publisher-verified asset hashes are configured; downloaded assets are NOT verified and runtime readiness does not prove file integrity."


def _local_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json_with_heartbeat(url: str, payload: dict, timeout: int, label: str) -> dict:
    """Keep the installer visibly alive while a CPU-only LLM is generating."""
    result: dict[str, dict] = {}
    error: list[BaseException] = []

    def _request() -> None:
        try:
            result["value"] = _post_json(url, payload, timeout=timeout)
        except BaseException as exc:  # propagate the original network/timeout error
            error.append(exc)

    worker = threading.Thread(target=_request, name="rightly-preflight-request", daemon=True)
    started = time.monotonic()
    worker.start()
    while worker.is_alive():
        elapsed = int(time.monotonic() - started)
        print(f"{label}: vẫn đang xử lý ({elapsed}s)…", flush=True)
        worker.join(timeout=10)
    if error:
        raise error[0]
    return result["value"]


def _check_machine(failures: list[str]) -> None:
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        failures.append("Rightly offline requires Windows 10/11 x64")
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                        ("available_extended", ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            ram_gb = status.total / (1024 ** 3)
            if ram_gb < 8:
                failures.append(f"At least 8 GB RAM is required (detected {ram_gb:.1f} GB)")
    except Exception as exc:
        failures.append(f"Could not verify RAM requirement: {exc}")
    try:
        free_gb = shutil.disk_usage(ROOT).free / (1024 ** 3)
        if free_gb < 25:
            failures.append(f"At least 25 GB free disk space is required (detected {free_gb:.1f} GB)")
    except Exception as exc:
        failures.append(f"Could not verify free disk space: {exc}")


def run() -> int:
    from app.config import load_settings

    settings = load_settings()
    failures: list[str] = []
    assets_verified, asset_note = _asset_verification_note()
    print(asset_note)
    _check_machine(failures)
    if settings.llm_backend != "local" or not settings.offline_mode:
        failures.append(".env must set LLM_BACKEND=local and OFFLINE_MODE=true")

    model_dir = Path(settings.whisper_model_path)
    if not model_dir.is_absolute():
        model_dir = ROOT / model_dir
    required_whisper = ["config.json", "model.bin", "tokenizer.json"]
    missing = [name for name in required_whisper if not (model_dir / name).exists()]
    if missing:
        failures.append(f"faster-whisper model missing: {', '.join(missing)}")
    else:
        try:
            print("Checking local ASR model…", flush=True)
            from app.asr.whisper_asr import WhisperASR

            WhisperASR(model_path=str(model_dir), device=settings.whisper_device).check_availability()
            # Force the model constructor now, while setup still has a useful
            # error channel; runtime must never download on first microphone use.
            WhisperASR(model_path=str(model_dir), device=settings.whisper_device)._load()
        except Exception as exc:
            failures.append(f"faster-whisper could not load locally: {exc}")

    piper_path = Path(settings.piper_model_path)
    if not piper_path.is_absolute():
        piper_path = ROOT / piper_path
    if not piper_path.exists() or not piper_path.with_suffix(piper_path.suffix + ".json").exists():
        failures.append(f"Piper voice missing: {piper_path}")
    else:
        try:
            print("Checking Vietnamese Piper voice…", flush=True)
            from app.tts.piper_tts import PiperTTS

            out = Path(tempfile.gettempdir()) / "rightly_preflight.wav"
            PiperTTS(piper_path).synthesize("Xin chào, Rightly đã sẵn sàng.", out)
            if not out.exists() or out.stat().st_size < 64:
                failures.append("Vietnamese Piper voice returned an empty WAV")
            out.unlink(missing_ok=True)
        except Exception as exc:
            failures.append(f"Piper synthesis failed: {exc}")
    piper_en = Path(settings.piper_model_path_en)
    if not piper_en.is_absolute():
        piper_en = ROOT / piper_en
    if not piper_en.exists() or not piper_en.with_suffix(piper_en.suffix + ".json").exists():
        failures.append(f"English Piper voice missing: {piper_en}")
    else:
        try:
            print("Checking English Piper voice…", flush=True)
            from app.tts.piper_tts import PiperTTS

            out_en = Path(tempfile.gettempdir()) / "rightly_preflight_en.wav"
            PiperTTS(piper_en).synthesize("Rightly is ready to help.", out_en)
            if not out_en.exists() or out_en.stat().st_size < 64:
                failures.append("English Piper voice returned an empty WAV")
            out_en.unlink(missing_ok=True)
        except Exception as exc:
            failures.append(f"English Piper synthesis failed: {exc}")

    try:
        tags = _local_json("http://127.0.0.1:11434/api/tags")
        names = {str(item.get("name", "")) for item in tags.get("models", [])}
        if settings.ollama_model not in names and not any(
            name.split(":", 1)[0] == settings.ollama_model.split(":", 1)[0] for name in names
        ):
            failures.append(f"Ollama model not pulled: {settings.ollama_model}")
    except Exception as exc:
        failures.append(f"Ollama is not ready on localhost: {exc}")

    # Load the selected local LLM before declaring setup complete.
    print("Checking local Ollama response (CPU-only machines may take a while)...", flush=True)
    try:
        result = _post_json_with_heartbeat(
            "http://127.0.0.1:11434/api/generate",
            {"model": settings.ollama_model, "prompt": "Reply with exactly OK.", "stream": False},
            timeout=PREFLIGHT_CHAT_TIMEOUT_S,
            label="Đang nạp LLM local",
        )
        if not str(result.get("response", "")).strip():
            failures.append("Ollama model returned an empty smoke-test response")
    except Exception as exc:
        failures.append(f"Ollama model smoke test failed: {exc}")

    # Verify the exact launcher contract on a temporary loopback port.
    server = None
    try:
        env = os.environ.copy()
        env["PORT"] = "8011"
        server = subprocess.Popen([sys.executable, str(ROOT / "webhook_server.py")], cwd=ROOT,
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ready = False
        for _ in range(45):
            try:
                health = _local_json("http://127.0.0.1:8011/health")
                if health.get("status") == "ok" and health.get("llm_ready") is True:
                    ready = True
                    break
            except Exception:
                time.sleep(1)
        if not ready:
            failures.append("Temporary Rightly server did not become ready on /health")
        else:
            print("Checking local Rightly chat endpoint…", flush=True)
            smoke = _post_json_with_heartbeat(
                "http://127.0.0.1:8011/api/chat",
                {
                    "session_id": "preflight",
                    "text": "Xin chào, hãy trả lời ngắn gọn OK.",
                    "lang": "vi",
                },
                timeout=PREFLIGHT_CHAT_TIMEOUT_S,
                label="Đang kiểm tra câu trả lời Rightly",
            )
            if not str(smoke.get("reply", "")).strip():
                failures.append("Local chat smoke test returned an empty reply")
    except Exception as exc:
        failures.append(f"Local server/chat smoke test failed: {exc}")
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    if failures:
        print("OFFLINE PREFLIGHT FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    suffix = "; asset checksums were configured" if assets_verified else "; asset checksums were NOT verified"
    print("OFFLINE PREFLIGHT OK: LLM + ASR assets + Piper voice are ready" + suffix)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
