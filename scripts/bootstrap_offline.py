"""Bootstrap the 100% offline stack on the TARGET machine (one command).

This downloads NOTHING on the developer machine - it is meant to be pulled
together with the repo onto the demo PC (i5 + 16GB DDR5 + RTX 3060 Ti 8GB)
and run there exactly once:

    python scripts/bootstrap_offline.py --all

It fetches everything the cloud stack has already learned to do, locally:
  1. python deps ................. requirements.txt + optional (incl. torch CUDA)
  2. Ollama server + LLM model ... qwen2.5:3b-instruct-q4_k_m (~2GB,
                                    balanced default for fast CPU chat)
  3. faster-whisper ASR weights . Systran/faster-whisper-small (local-only)
  4. Dense embeddings ........... intfloat/multilingual-e5-small + rebuild
                                    data/chunks/{real,demo}_embeddings.npz so
                                    hybrid retrieval works with zero network
  5. Piper voices ................ Vietnamese + English neural voices

Afterwards the demo runs fully offline: no internet, no cloud API keys.
Also see docs/offline_runbook.md and scripts/check_local_llm.py.

Flags:
  --all            do every step (default when no step flag given)
  --deps           install python dependencies
  --ollama         install Ollama (if missing) + pull the model
  --asr            download PhoWhisper weights into the HF cache
  --embeddings     download e5-small + build embedding caches (.npz)
  --piper          download optional piper voice files into data/voices/
  --model NAME     Ollama model to pull (default: qwen2.5:3b-instruct-q4_k_m)
  --env offline    write a fresh .env (only if it does not exist yet)
                   --env online   keeps/enables pateway cloud backend
  --skip-torch     do not pip-install torch/sentence-transformers (use existing)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:  # Windows consoles may still default to cp1252 during a child process.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OLLAMA_DEFAULT_MODEL = "qwen2.5:3b-instruct-q4_k_m"
OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_SERVER = "http://localhost:11434"

HF_E5 = "intfloat/multilingual-e5-small"
HF_WHISPER = "Systran/faster-whisper-small"

PIPER_VOICES_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN"
    "/vais1000/medium/vi_VN-vais1000-medium"
)
PIPER_EN_VOICES_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US"
    "/lessac/medium/en_US-lessac-medium"
)
VOICES_DIR = ROOT / "data" / "voices"
ASSET_MANIFEST_PATH = ROOT / "scripts" / "asset_manifest.json"


def _asset_sha256(url: str, target: Path) -> str | None:
    """Read an explicitly verified hash; absent entries remain unverifiable."""
    try:
        manifest = json.loads(ASSET_MANIFEST_PATH.read_text(encoding="utf-8"))
        entry = manifest.get("assets", {}).get(target.name) or manifest.get("assets", {}).get(url)
        digest = str(entry.get("sha256", "")).strip().lower() if isinstance(entry, dict) else ""
        return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else None
    except (OSError, ValueError, TypeError):
        return None


def _verify_sha256(path: Path, expected: str) -> None:
    actual = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            actual.update(block)
    got = actual.hexdigest().lower()
    if got != expected.lower():
        raise RuntimeError(
            f"Kiểm tra toàn vẹn thất bại cho {path.name}: nhận {got}, "
            f"mong đợi {expected.lower()}. File bị loại bỏ; hãy chạy lại để tải lại."
        )

TIMEOUT_S = 3600

# Downloads are deliberately retryable.  Hugging Face and Ollama both keep
# completed blobs locally, while Piper uses a .part file below.  A transient
# DNS reset or Wi-Fi drop therefore no longer throws away a multi-GB download.
DOWNLOAD_RETRIES = max(1, int(os.environ.get("RIGHTLY_DOWNLOAD_RETRIES", "12")))
DOWNLOAD_RETRY_DELAY_S = max(
    1.0, float(os.environ.get("RIGHTLY_DOWNLOAD_RETRY_DELAY", "8"))
)
DOWNLOAD_RETRY_MAX_DELAY_S = max(
    DOWNLOAD_RETRY_DELAY_S,
    float(os.environ.get("RIGHTLY_DOWNLOAD_RETRY_MAX_DELAY", "120")),
)
# A stalled HTTP socket should be released so the next attempt can resume;
# this is separate from the long timeout used for a healthy Ollama process.
DOWNLOAD_SOCKET_TIMEOUT_S = max(
    15.0, float(os.environ.get("RIGHTLY_DOWNLOAD_SOCKET_TIMEOUT", "90"))
)
PYPI_PROBE_URL = "https://pypi.org/simple/"
HF_PROBE_URL = "https://huggingface.co/"
OLLAMA_REGISTRY_PROBE_URL = "https://registry.ollama.ai/v2/"


def _step(title: str) -> None:
    print(f"\n=== {title} ===")


def _check_hardware_requirements() -> None:
    """Fail before downloads when the target cannot run the offline stack."""
    failures: list[str] = []
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        failures.append("Windows 10/11 x64 is required")
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                        ("extended", ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            ram_gb = status.total / (1024 ** 3)
            if ram_gb < 8:
                failures.append(f"at least 8 GB RAM is required (detected {ram_gb:.1f} GB)")
    except Exception as exc:
        failures.append(f"could not verify RAM: {exc}")
    try:
        free_gb = shutil.disk_usage(ROOT).free / (1024 ** 3)
        if free_gb < 25:
            failures.append(f"at least 25 GB free disk space is required (detected {free_gb:.1f} GB)")
    except Exception as exc:
        failures.append(f"could not verify free disk space: {exc}")
    if failures:
        raise SystemExit("Hardware requirement check failed:\n- " + "\n- ".join(failures))


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("   $", " ".join(cmd))
    kwargs.setdefault("check", True)
    return subprocess.run(cmd, cwd=ROOT, timeout=TIMEOUT_S, **kwargs)


def _probe_network(url: str) -> bool:
    """Return whether a remote host is reachable without requiring a 2xx body."""
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Rightly-Setup/1.0"},
            method="HEAD",
        )
        with urllib.request.urlopen(request, timeout=10):  # noqa: S310
            return True
    except urllib.error.HTTPError as exc:
        # A 401/403/404 still proves DNS + TLS + routing are working.  5xx is
        # a service/network failure and should be retried.
        return exc.code < 500
    except Exception:
        return False


def _wait_before_retry(label: str, attempt: int, probe_url: str | None) -> None:
    """Wait with exponential backoff, keeping the existing local partial data."""
    delay = min(
        DOWNLOAD_RETRY_MAX_DELAY_S,
        DOWNLOAD_RETRY_DELAY_S * (2 ** max(0, attempt - 1)),
    )
    print(
        f"   Mạng chưa ổn định khi {label}; giữ phần đã tải và thử lại "
        f"sau khoảng {delay:.0f}s (lần {attempt}/{DOWNLOAD_RETRIES - 1})..."
    )
    time.sleep(delay)
    if probe_url and not _probe_network(probe_url):
        print("   Kiểm tra mạng vẫn chưa thành công; sẽ tiếp tục chờ và thử lại.")
    elif probe_url:
        print("   Kết nối đã phản hồi; tiếp tục đúng phần còn thiếu.")


def _retry_call(label: str, action, *, probe_url: str | None = None):
    """Retry a network-backed operation without deleting its local cache."""
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            return action()
        except Exception as exc:  # provider libraries use several exception types
            last_error = exc
            if attempt >= DOWNLOAD_RETRIES:
                break
            _wait_before_retry(label, attempt, probe_url)
    assert last_error is not None
    raise RuntimeError(
        f"{label} thất bại sau {DOWNLOAD_RETRIES} lần thử. "
        "Phần đã tải vẫn được giữ lại; hãy chạy lại bộ cài khi mạng ổn định hơn."
    ) from last_error


def _run_resumable(cmd: list[str], label: str, *, probe_url: str | None = None) -> None:
    """Rerun a resumable CLI download (notably ``ollama pull``) after outages."""
    last_code = 1
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        result = _run(cmd, check=False)
        last_code = result.returncode
        if last_code == 0:
            return
        if attempt >= DOWNLOAD_RETRIES:
            break
        _wait_before_retry(label, attempt, probe_url)
    raise subprocess.CalledProcessError(last_code, cmd)


def _download_resumable(url: str, target: Path, *, expected_sha256: str | None = None) -> None:
    """Download one HTTP asset with Range resume and atomic completion."""
    if target.exists() and target.stat().st_size > 0:
        if expected_sha256:
            try:
                _verify_sha256(target, expected_sha256)
            except RuntimeError:
                target.unlink()
            else:
                print(f"   {target.name} already present (SHA-256 OK)")
                return
        else:
            print(f"   {target.name} already present")
            return

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        offset = part.stat().st_size if part.exists() else 0
        try:
            headers = {"User-Agent": "Rightly-Setup/1.0"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=DOWNLOAD_SOCKET_TIMEOUT_S) as response:  # noqa: S310
                status = getattr(response, "status", response.getcode())
                # If a server ignores Range (HTTP 200), restart only the .part
                # file.  The final target remains untouched until completion.
                if offset and status == 416:
                    part.unlink(missing_ok=True)
                    continue
                mode = "ab" if offset and status == 206 else "wb"
                content_length = response.headers.get("Content-Length")
                expected_size = None
                if content_length:
                    expected_size = int(content_length) + (offset if status == 206 else 0)
                with part.open(mode) as out:
                    shutil.copyfileobj(response, out)
            if (
                part.exists()
                and part.stat().st_size > 0
                and (expected_size is None or part.stat().st_size >= expected_size)
            ):
                os.replace(part, target)
                if expected_sha256:
                    try:
                        _verify_sha256(target, expected_sha256)
                    except RuntimeError:
                        target.unlink(missing_ok=True)
                        raise
                print(f"   saved {target.name}")
                return
            if expected_size is not None:
                raise OSError(
                    f"incomplete response ({part.stat().st_size if part.exists() else 0}/"
                    f"{expected_size} bytes)"
                )
            raise OSError("empty response")
        except Exception as exc:
            last_error = exc
            if attempt >= DOWNLOAD_RETRIES:
                break
            _wait_before_retry(label=f"tải {target.name}", attempt=attempt, probe_url=url)
    assert last_error is not None
    raise RuntimeError(
        f"Không thể tải {target.name} sau {DOWNLOAD_RETRIES} lần thử. "
        f"Phần tạm vẫn còn tại {part}; chạy lại sẽ tiếp tục từ đó."
    ) from last_error


def _pip(venv_python: str, *args: str) -> None:
    """Install one pip command while preserving options and their values.

    ``-r`` must stay adjacent to its requirements-file argument.  The old
    implementation looped over each argument, turning ``_pip(py, "-r",
    "requirements.txt")`` into ``pip install -r`` and failing immediately.
    """
    label = " ".join(args)
    _step(f"pip install {label}")
    # A broken global pip cache should never block or spam the one-click
    # installer. Offline assets are stored in data/, not pip's cache.
    _retry_call(
        f"cài thư viện {label}",
        lambda: _run([venv_python, "-m", "pip", "install", "--no-cache-dir", *args]),
        probe_url=PYPI_PROBE_URL,
    )


def _venv_python() -> str:
    if os.name == "nt":
        return str(ROOT / ".venv" / "Scripts" / "python.exe")
    return str(ROOT / ".venv" / "bin" / "python")


def _ensure_venv(args: argparse.Namespace) -> str:
    py = _venv_python()
    if not Path(py).exists():
        _step("Creating .venv")
        _run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    if not args.skip_torch:
        _pip(py, "torch")  # default wheel ships CUDA on Windows
    return py


# ---------------------------------------------------------------- deps


def install_deps(args: argparse.Namespace) -> None:
    py = _venv_python()
    _pip(py, "-r", str(ROOT / "requirements.txt"))
    _pip(py, "-r", str(ROOT / "requirements-optional.txt"))
    if not args.skip_torch:
        _pip(py, "sentence-transformers", "transformers", "av", "huggingface_hub")


# ---------------------------------------------------------------- ollama


def _ollama_bin() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    # Windows installers do not refresh PATH for the current cmd process.
    # Resolve the executable from the standard per-user/system locations so a
    # one-click setup can continue immediately after silent installation.
    candidates: list[Path] = []
    for raw in (
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
    ):
        if raw:
            base = Path(raw)
            candidates.extend(
                (
                    base / "Programs" / "Ollama" / "ollama.exe",
                    base / "Ollama" / "ollama.exe",
                    base / "Ollama" / "bin" / "ollama.exe",
                )
            )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _ollama_server_up() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_SERVER}/api/tags", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def install_ollama(args: argparse.Namespace) -> None:
    model = args.model or OLLAMA_DEFAULT_MODEL
    bin_path = _ollama_bin()
    if _ollama_server_up():
        print(f"Ollama already running at {OLLAMA_SERVER}")
    else:
        if bin_path is None:
            if os.name != "nt":
                raise SystemExit(
                    "Ollama not found. Install manually: https://ollama.com/download "
                    "then re-run with --ollama"
                )
            _step(f"Downloading Ollama installer from {OLLAMA_SETUP_URL}")
            tmp = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
            _download_resumable(OLLAMA_SETUP_URL, tmp)
            _step("Installing Ollama (silent)")
            _run([str(tmp), "/S"], check=False)
            # Re-resolve after installation; PATH in this process is stale.
            bin_path = _ollama_bin()
            if bin_path is None:
                raise SystemExit(
                    "Ollama installer finished but ollama.exe was not found. "
                    "Restart Windows or install Ollama manually, then retry."
                )
            # The silent installer may not start the service on older images.
            subprocess.Popen([bin_path, "serve"], cwd=ROOT)
        else:
            _step("Starting Ollama server")
            subprocess.Popen([bin_path, "serve"], cwd=ROOT)

        for _ in range(30):
            if _ollama_server_up():
                break
            print("   waiting for Ollama server ...")
            time.sleep(2)
        if not _ollama_server_up():
            raise SystemExit(
                "Ollama server did not start. Open the Ollama app manually, "
                "then re-run: python scripts/bootstrap_offline.py --ollama"
            )

    bin_path = _ollama_bin()
    if not bin_path:
        raise SystemExit("Ollama server is reachable but ollama.exe is unavailable for model download.")
    _step(f"ollama pull {model}  (model size depends on hardware choice)")
    # Ollama stores completed layers in its content-addressed cache.  Running
    # pull again after a DNS/connection failure continues from those layers.
    _run_resumable(
        [bin_path, "pull", model],
        f"tải model Ollama {model}",
        probe_url=OLLAMA_REGISTRY_PROBE_URL,
    )

    _step("Model listing")
    _run([bin_path, "list"])


# ---------------------------------------------------------------- hf weights


def _hf_download(repo: str, ignore: tuple[str, ...] = ()) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("pip install huggingface_hub first (see --deps)") from exc
    kwargs = {"allow_patterns": ["*"]}
    if ignore:
        kwargs["ignore_patterns"] = list(ignore)
    _retry_call(
        f"tải model {repo}",
        lambda: snapshot_download(repo_id=repo, **kwargs),
        probe_url=HF_PROBE_URL,
    )


def download_asr_weights(args: argparse.Namespace) -> None:
    target = ROOT / "data" / "models" / "faster-whisper-small"
    target.mkdir(parents=True, exist_ok=True)
    _step(f"Downloading faster-whisper weights ({HF_WHISPER})")
    from huggingface_hub import snapshot_download
    _retry_call(
        f"tải ASR {HF_WHISPER}",
        lambda: snapshot_download(
            repo_id=HF_WHISPER,
            local_dir=str(target),
            allow_patterns=[
                "config.json",
                "model.bin",
                "tokenizer.json",
                "vocabulary.*",
                "preprocessor_config.json",
            ],
        ),
        probe_url=HF_PROBE_URL,
    )


def build_embeddings(args: argparse.Namespace) -> None:
    _step(f"Downloading embedding model ({HF_E5})")
    _hf_download(HF_E5, ignore=("*.onnx*",))
    _step("Building embedding caches into data/chunks/*.npz (GPU on 3060 Ti)")
    code = (
        "import sys;"
        "from pathlib import Path;"
        "from app.retrieval.document_loader import DocumentLoader;"
        "from app.retrieval.hybrid_retriever import DenseIndex;"
        "chunks_dir = Path('data/chunks');"
        "for name in ('real_chunks.jsonl', 'demo_chunks.jsonl'):"
        "    f = chunks_dir / name;"
        "    if not f.exists():"
        "        print('skip', f);"
        "        continue;"
        "    cache = chunks_dir / name.replace('_chunks.jsonl', '_embeddings.npz');"
        "    DenseIndex.from_chunks(DocumentLoader.load_chunks(f), cache_path=cache);"
        "    print('built', cache)"
    )
    _run([_venv_python(), "-c", code])


def download_piper_voice(args: argparse.Namespace) -> None:
    _step("Downloading Piper voices (Vietnamese + English)")
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    voices = (
        (PIPER_VOICES_URL, "vi_VN-vais1000-medium"),
        (PIPER_EN_VOICES_URL, "en_US-lessac-medium"),
    )
    for base_url, voice_name in voices:
        for suffix in (".onnx", ".onnx.json"):
            url = base_url + suffix
            target = VOICES_DIR / f"{voice_name}{suffix}"
            _download_resumable(url, target, expected_sha256=_asset_sha256(url, target))


# ---------------------------------------------------------------- env


def _env_offline_lines(model: str) -> list[str]:
    return [
        "APP_MODE=local",
        "ASR_BACKEND=whisper",
        "WHISPER_MODEL=small",
        "WHISPER_MODEL_PATH=data/models/faster-whisper-small",
        "RETRIEVAL_BACKEND=bm25",
        "LLM_BACKEND=local",
        "OLLAMA_BASE_URL=http://localhost:11434/v1",
        f"OLLAMA_MODEL={model}",
        "LLM_TIMEOUT_SECONDS=180",
        "TTS_BACKEND=piper",
        "PIPER_MODEL_PATH=data/voices/vi_VN-vais1000-medium.onnx",
        "PIPER_MODEL_PATH_EN=data/voices/en_US-lessac-medium.onnx",
        "OFFLINE_MODE=true",
        "LOCAL_MEMORY_PATH=data/private_cache/memory.sqlite3",
        "LOCAL_MEMORY_RETENTION_DAYS=90",
        "DELETE_RAW_AUDIO_AFTER_SESSION=true",
        "SAVE_TRANSCRIPTS=false",
        "PII_SCRUB_OUTBOUND=true",
        "RETRIEVER_RERANK=false",
        "RETRIEVER_GATE=bm25_dense",
    ]


def _env_online_lines() -> list[str]:
    return [
        "APP_MODE=local",
        "ASR_BACKEND=phowhisper",
        "RETRIEVAL_BACKEND=hybrid",
        "LLM_BACKEND=pateway",
        "LLM_FALLBACK_BACKEND=groq",
        "TTS_BACKEND=google",
        "DELETE_RAW_AUDIO_AFTER_SESSION=true",
        "SAVE_TRANSCRIPTS=false",
        "PII_SCRUB_OUTBOUND=true",
        "RETRIEVER_RERANK=false",
        "RETRIEVER_GATE=bm25_dense",
    ]


def write_env(args: argparse.Namespace) -> None:
    env_file = ROOT / ".env"
    if env_file.exists() and not args.force_env:
        print(
            f"\n.env already exists at {env_file} - I will NOT overwrite it.\n"
            f"To switch modes edit it yourself (see docs/offline_runbook.md) or run:\n"
            f"    --env online   -> keep cloud LLM\n"
            f"    --env offline  -> local LLM\n"
        )
        return
    lines = _env_offline_lines(args.model or OLLAMA_DEFAULT_MODEL)
    if args.env == "online":
        lines = _env_online_lines()
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {env_file} ({args.env} mode)")


# ---------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--deps", action="store_true")
    parser.add_argument("--ollama", action="store_true")
    parser.add_argument("--asr", action="store_true")
    parser.add_argument("--embeddings", action="store_true")
    parser.add_argument("--piper", action="store_true")
    parser.add_argument("--env", choices=("offline", "online"), default="offline")
    parser.add_argument("--model", default=OLLAMA_DEFAULT_MODEL)
    parser.add_argument("--skip-torch", action="store_true")
    parser.add_argument("--force-env", action="store_true", help="replace .env with verified offline settings")
    args = parser.parse_args()

    _check_hardware_requirements()

    print(
        "\nRightly offline bootstrap - downloads everything ONCE into this "
        "machine's local cache (models, voices, embeddings).\n"
        "Nothing is uploaded anywhere; after this finishes the demo runs "
        "100% offline.\n"
    )
    if not (args.all or args.deps or args.ollama or args.asr or args.embeddings or args.piper):
        args.all = True

    if args.all or args.deps:
        _ensure_venv(args)
        install_deps(args)
    if args.all or args.ollama:
        install_ollama(args)
    if args.all or args.asr:
        download_asr_weights(args)
    if args.all or args.embeddings:
        build_embeddings(args)
    if args.piper or args.all:
        download_piper_voice(args)
    write_env(args)

    print(
        "\n=== DONE. Full offline stack is ready on this machine. ===\n"
        "Next steps:\n"
        "  1. python scripts/check_local_llm.py\n"
        "  2. python scripts/run_mock_demo.py   (LLM_BACKEND=local from .env)\n"
        "Balanced local default: qwen2.5:3b-instruct-q4_k_m.\n"
        "Machines with >=8GB GPU may use qwen2.5:7b-instruct-q4_K_M.\n"
        "Switch back to cloud anytime:\n"
        "set LLM_BACKEND=pateway in .env.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
