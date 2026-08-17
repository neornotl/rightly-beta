"""Bootstrap the 100% offline stack on the TARGET machine (one command).

This downloads NOTHING on the developer machine - it is meant to be pulled
together with the repo onto the demo PC (i5 + 16GB DDR5 + RTX 3060 Ti 8GB)
and run there exactly once:

    python scripts/bootstrap_offline.py --all

It fetches everything the cloud stack has already learned to do, locally:
  1. python deps ................. requirements.txt + optional (incl. torch CUDA)
  2. Ollama server + LLM model ... qwen2.5:7b-instruct-q4_k_m (~4.8GB VRAM,
                                    JSON-stable, council round-26 pick)
  3. PhoWhisper ASR weights ...... vinai/PhoWhisper-base (~1GB, CPU inference)
  4. Dense embeddings ........... intfloat/multilingual-e5-small + rebuild
                                    data/chunks/{real,demo}_embeddings.npz so
                                    hybrid retrieval works with zero network
  5. (optional --piper) ......... vi_VN piper voice files (later integration)

Afterwards the demo runs fully offline: no internet, no cloud API keys.
Also see docs/offline_runbook.md and scripts/check_local_llm.py.

Flags:
  --all            do steps 1-3-4 (default when no step flag given)
  --deps           install python dependencies
  --ollama         install Ollama (if missing) + pull the model
  --asr            download PhoWhisper weights into the HF cache
  --embeddings     download e5-small + build embedding caches (.npz)
  --piper          download optional piper voice files into data/voices/
  --model NAME     Ollama model to pull (default: qwen2.5:7b-instruct-q4_k_m)
  --env offline    write a fresh .env (only if it does not exist yet)
                   --env online   keeps/enables pateway cloud backend
  --skip-torch     do not pip-install torch/sentence-transformers (use existing)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OLLAMA_DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_k_m"
OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_SERVER = "http://localhost:11434"

HF_E5 = "intfloat/multilingual-e5-small"
HF_PHOWHISPER = "vinai/PhoWhisper-base"

PIPER_VOICES_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/vi/vi_VN"
    "/vais1000/medium/vi_VN-vais1000-medium"
)
VOICES_DIR = ROOT / "data" / "voices"

TIMEOUT_S = 3600


def _step(title: str) -> None:
    print(f"\n=== {title} ===")


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("   $", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, timeout=TIMEOUT_S, **kwargs)


def _pip(venv_python: str, *pkgs: str) -> None:
    for pkg in pkgs:
        _step(f"pip install {pkg}")
        _run([venv_python, "-m", "pip", "install", pkg])


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
    return shutil.which("ollama")


def _ollama_server_up() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_SERVER}/api/tags", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def install_ollama(args: argparse.Namespace) -> None:
    model = args.model or OLLAMA_DEFAULT_MODEL
    if _ollama_server_up():
        print(f"Ollama already running at {OLLAMA_SERVER}")
    else:
        bin_path = _ollama_bin()
        if bin_path is None:
            if os.name != "nt":
                raise SystemExit(
                    "Ollama not found. Install manually: https://ollama.com/download "
                    "then re-run with --ollama"
                )
            _step(f"Downloading Ollama installer from {OLLAMA_SETUP_URL}")
            tmp = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
            urllib.request.urlretrieve(OLLAMA_SETUP_URL, tmp)  # noqa: S310
            _step("Installing Ollama (silent)")
            _run([str(tmp), "/S"], check=False)
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

    _step(f"ollama pull {model}  (~5GB, may take a while)")
    _run(["ollama", "pull", model])

    _step("Model listing")
    _run(["ollama", "list"])


# ---------------------------------------------------------------- hf weights


def _hf_download(repo: str, ignore: tuple[str, ...] = ()) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit("pip install huggingface_hub first (see --deps)") from exc
    kwargs = {"allow_patterns": ["*"]}
    if ignore:
        kwargs["ignore_patterns"] = list(ignore)
    snapshot_download(repo_id=repo, **kwargs)


def download_asr_weights(args: argparse.Namespace) -> None:
    _step(f"Downloading PhoWhisper weights ({HF_PHOWHISPER})")
    _hf_download(HF_PHOWHISPER)


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
    _step("Downloading optional piper voice (vi_VN vais1000 medium)")
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in (".onnx", ".onnx.json"):
        url = PIPER_VOICES_URL + suffix
        target = VOICES_DIR / f"vi_VN-vais1000-medium{suffix}"
        if target.exists() and target.stat().st_size > 0:
            print(f"   {target.name} already present")
            continue
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp, open(  # noqa: S310
            target, "wb"
        ) as out:
            shutil.copyfileobj(resp, out)
        print(f"   saved {target.name}")


# ---------------------------------------------------------------- env


def _env_offline_lines(model: str) -> list[str]:
    return [
        "APP_MODE=local",
        "ASR_BACKEND=phowhisper",
        "RETRIEVAL_BACKEND=hybrid",
        "LLM_BACKEND=local",
        "OLLAMA_BASE_URL=http://localhost:11434/v1",
        f"OLLAMA_MODEL={model}",
        "TTS_BACKEND=mock",
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
        "TTS_BACKEND=edge",
        "DELETE_RAW_AUDIO_AFTER_SESSION=true",
        "SAVE_TRANSCRIPTS=false",
        "PII_SCRUB_OUTBOUND=true",
        "RETRIEVER_RERANK=false",
        "RETRIEVER_GATE=bm25_dense",
    ]


def write_env(args: argparse.Namespace) -> None:
    env_file = ROOT / ".env"
    if env_file.exists():
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
    args = parser.parse_args()

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
    if args.piper:
        download_piper_voice(args)
    write_env(args)

    print(
        "\n=== DONE. Full offline stack is ready on this machine. ===\n"
        "Next steps:\n"
        "  1. python scripts/check_local_llm.py\n"
        "  2. python scripts/run_mock_demo.py   (LLM_BACKEND=local from .env)\n"
        "Demo machine notes (council round-26 pick): qwen2.5:7b-instruct-q4_k_m\n"
        "fits RTX 3060 Ti 8GB with ~1.5GB headroom for CUDA/embedding; if it is\n"
        "slow or fails, OLLAMA_MODEL=qwen3:8b (quality fallback, think=false) or\n"
        "qwen2.5:3b (emergency CPU). Switch back to cloud anytime:\n"
        "set LLM_BACKEND=pateway in .env.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
