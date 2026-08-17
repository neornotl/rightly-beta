"""Preflight: everything must pass before claiming the repo is ready.

Checks (in order):
1. Python version >= 3.10.
2. Config loads with safe defaults (mock mode).
3. Data files valid (scripts/validate_data.py).
4. All modules import cleanly (incl. adapters; lazy deps not required).
5. Test suite passes (pytest).
6. Lint passes (ruff check).
7. Mock demo runs end-to-end.
8. Eval R1-R4 run with fixtures.
9. No API keys leaked into repo files (excluding .env.example).

Usage:
    python scripts/preflight.py [--skip-tests] [--skip-eval]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RED = "\033[31m" if sys.platform != "win32" else ""
GREEN = "\033[32m" if sys.platform != "win32" else ""
RESET = "\033[0m" if sys.platform != "win32" else ""


def _run_py(args: list[str], cwd: Path = Path.cwd()) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )


def _check(name: str, fn) -> tuple[bool, str]:
    try:
        detail = fn()
        print(f"  [PASS] {name}" + (f" - {detail}" if detail else ""))
        return True, detail or ""
    except SystemExit as exc:
        code = int(exc.code or 1)
        print(f"  [FAIL] {name} (exit {code})")
        return False, f"exit {code}"
    except Exception as exc:
        print(f"  [FAIL] {name}: {exc}")
        return False, str(exc)


def _run_python(*args: str, cwd: Path = Path.cwd()) -> str:
    proc = _run_py(list(args), cwd)
    return (proc.stdout or "").strip()


def _run_module(module: str, *args: str) -> str:
    return _run_python("-m", module, *args)


def main() -> int:
    print("== Rightly preflight ==")
    passed: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    skip_tests = "--skip-tests" in sys.argv
    skip_eval = "--skip-eval" in sys.argv

    ok, d = _check("python version", _check_python)
    passed.append(("python version", d)) if ok else failed.append(("python version", d))
    ok, d = _check("config loads (mock)", _check_config)
    passed.append(("config (mock)", d)) if ok else failed.append(("config (mock)", d))
    ok, d = _check("all modules import", _check_imports)
    passed.append(("imports", d)) if ok else failed.append(("imports", d))
    ok, d = _check("data validation", _check_data)
    passed.append(("data validation", d)) if ok else failed.append(("data validation", d))
    ok, d = _check("secret scan", _check_secrets)
    passed.append(("secret scan", d)) if ok else failed.append(("secret scan", d))
    if not skip_tests:
        ok, d = _check("pytest", _check_tests)
        passed.append(("pytest", d)) if ok else failed.append(("pytest", d))
    ok, d = _check("ruff check", _check_lint)
    passed.append(("ruff", d)) if ok else failed.append(("ruff", d))
    ok, d = _check("mock demo", _check_demo)
    passed.append(("mock demo", d)) if ok else failed.append(("mock demo", d))
    if not skip_eval:
        ok, d = _check("eval R1-R4", _check_eval)
        passed.append(("eval R1-R4", d)) if ok else failed.append(("eval R1-R4", d))

    print("\n== Summary ==")
    for name, detail in passed:
        print(f"  [PASS] {name}")
    for name, detail in failed:
        print(f"  [FAIL] {name} - {detail}")
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 0 if not failed else 1


def _check_python() -> str:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        raise RuntimeError(f"Python {sys.version} too old; need >=3.10")
    return f"{major}.{minor}"


def _check_config() -> str:
    from app.config import load_settings

    s = load_settings()
    return f"app_mode={s.app_mode}"


def _check_imports() -> str:
    modules = [
        "app.config",
        "app.schemas",
        "app.logging_utils",
        "app.asr.base",
        "app.asr.mock_asr",
        "app.asr.phowhisper_asr",
        "app.retrieval.base",
        "app.retrieval.bm25_retriever",
        "app.retrieval.document_loader",
        "app.llm.base",
        "app.llm.mock_llm",
        "app.llm.gemini_llm",
        "app.llm.groq_llm",
        "app.safety.rules",
        "app.safety.router",
        "app.safety.policy",
        "app.tts.base",
        "app.tts.mock_tts",
        "app.tts.edge_tts",
        "app.dialogue.state_machine",
        "app.dialogue.commands",
        "app.pipeline",
        "app.cli",
        "eval.common",
        "eval.wer",
        "eval.retrieval",
        "eval.routing",
        "eval.latency",
        "eval.run_all",
    ]
    for mod in modules:
        __import__(mod)
    return f"{len(modules)} modules"


def _check_data() -> str:
    return _run_python("scripts/validate_data.py")


def _check_secrets() -> str:
    """Scan repo files for leaked key patterns; .env/.env.example and
    gitignored artifacts (.venv, caches) are allowed."""
    pattern = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,})")
    ignore_dirs = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    ignore_names = {".env", ".env.example", "RECORD"}
    hits = []
    for path in Path.cwd().rglob("*"):
        if path.is_file():
            if any(p in ignore_dirs for p in path.parts):
                continue
            if path.name in ignore_names or path.suffix in {".pyc", ".wav", ".mp3"}:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern.search(content):
                hits.append(str(path))
    if hits:
        raise RuntimeError(f"possible key leak: {hits}")
    return "no key patterns found"


def _check_tests() -> str:
    proc = _run_py(["-m", "pytest", "-q"])
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").splitlines()[-5:]) + (proc.stderr or "")[-500:]
        raise RuntimeError(f"pytest failed:\n{tail}")
    return (proc.stdout or "").strip().splitlines()[-1].strip()


def _check_lint() -> str:
    proc = _run_py(["-m", "ruff", "check", "."], cwd=Path.cwd())
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "")[-800:] + (proc.stderr or "")[-300:])
    return "clean"


def _check_demo() -> str:
    out = _run_module("app.cli", "--transcript", "Đăng ký khai sinh cần giấy gì?", "--once")
    if "zone=YELLOW" not in out:
        raise RuntimeError(f"demo output unexpected:\n{out[-800:]}")
    return "end-to-end mock ok"


def _check_eval() -> str:
    out = _run_module("eval.run_all")
    if "SYNTHETIC DEMO" not in out and "wrote results" not in out:
        raise RuntimeError(f"eval failed:\n{out[-800:]}")
    return "results written"


if __name__ == "__main__":
    raise SystemExit(main())
