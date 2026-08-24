# -*- coding: utf-8 -*-
"""Rightly-Setup: one-file EXE installer (built with PyInstaller).

Chạy trên máy trống cũng tự động được hết, từng bước hiện rõ để quay clip:
  [1] Kiểm tra/cài Python (winget)
  [2] Tạo .venv riêng
  [3] Cài dependencies (nhẹ: BM25 retrieval, không cần torch)
  [4] Nhận diện phần cứng -> ghi .env (model nhẹ-mạnh phù hợp máy)
  [5] Ollama: tải model qwen2.5:7b-instruct-q4_K_M (resume khi rớt mạng)
  [6] Shortcut Desktop + khởi động Rightly
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

MODEL = "qwen2.5:7b-instruct-q4_K_M"
INSTALL_HINTS = True

try:  # exe console mặc định cp1252 -> ép UTF-8 để không crash tiếng Việt
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run(cmd, **kw):
    print(f"  $ {' '.join(map(str, cmd))}", flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def step(n, total, title):
    bar = "=" * 52
    print(f"\n[{n}/{total}] {title}\n{bar}", flush=True)


BUNDLE_ITEMS = [
    "app", "web", "data", "scripts",
    "webhook_server.py", "requirements-deploy.txt",
    "Rightly.bat", "TaiOllamaModel.bat", "README-NGUOI-DUNG.txt",
    "LICENSE", ".env.example",
]


def extract_bundle(target: Path) -> None:
    src = Path(getattr(sys, "_MEIPASS", "."))
    print(f"  Giai nen runtime -> {target}", flush=True)
    for it in BUNDLE_ITEMS:
        s = src / it
        d = target / it
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        elif s.exists():
            shutil.copy2(s, d)
    print("  Extract xong.", flush=True)


def find_python() -> str | None:
    for cand in ("python", "py"):
        if shutil.which(cand):
            return cand
    return None


def ensure_python() -> str:
    step(1, 6, "KIEM TRA PYTHON")
    py = find_python()
    if py:
        print(f"  Da co Python ({py})")
        return py
    print("  May chua co Python -> tu dong cai qua winget...")
    run(["winget", "install", "-e", "--id", "Python.Python.3.12",
         "--accept-source-agreements", "--accept-package-agreements"])
    # refresh PATH from registry (rough): rely on restart message if still missing
    py = find_python()
    if not py:
        print("\n!!! Chua thay python trong PATH. Hay DONG cua so nay, MO CUA SO MOI va chay lai Setup.")
        input("Nhan Enter de thoat...")
        sys.exit(1)
    return py


def ensure_venv(py: str) -> tuple[str, str]:
    step(2, 6, "TAO MOI TRUONG RIENG (.venv)")
    root = Path.cwd()
    venv_py = root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python")
    if not venv_py.exists():
        run([py, "-m", "venv", ".venv"])
    if not venv_py.exists():
        print("!!! Loi tao .venv"); input("Enter de thoat..."); sys.exit(1)
    print("  .venv OK:", venv_py)
    return str(venv_py), str(root)


def install_deps(venv_py: str, root: Path):
    step(3, 6, "CAI THU VIEN (lan dau ~3 phut)")
    pip = str(Path(venv_py).with_name("pip.exe"))
    run([pip, "install", "--upgrade", "pip", "-q"])
    rc = run([pip, "install", "-r", str(root / "requirements-deploy.txt"),
              "pypdf", "python-docx", "-q"]).returncode
    if rc != 0:
        print("  ! pip loi, thu lai khong -q de xem chi tiet...")
        run([pip, "install", "-r", str(root / "requirements-deploy.txt"),
             "pypdf", "python-docx"])


def write_env(root: Path) -> None:
    step(4, 6, "NHAN DIEN CAU HINH MAY + TAO FILE .ENV")
    det = Path(root) / "scripts" / "detect_hardware.py"
    run([sys.executable, str(det)]) if getattr(sys, "frozen", False) else run(
        [Path(root).joinpath(".venv", "Scripts", "python.exe"), str(det)])

    gem = ""
    try:
        gem = input("  (TUY CHON) Dán GEMINI_API_KEY để trả lời chính xác hơn qua cloud [Enter = bỏ qua]: ").strip()
    except EOFError:
        pass

    lines = [
        f"# Rightly .env - sinh boi Setup ngay {time.strftime('%Y-%m-%d')}",
        "APP_MODE=local",
        "ASR_BACKEND=whisper",
        "RETRIEVAL_BACKEND=bm25",
        "TTS_BACKEND=mock",
    ]
    if gem:
        lines += ["LLM_BACKEND=gemini", "LLM_FALLBACK_BACKEND=local",
                  f"GEMINI_API_KEY={gem}", "GEMINI_MODEL=gemini-2.5-flash",
                  "GEMINI_THINKING_BUDGET=512"]
    else:
        lines += ["LLM_BACKEND=local"]
    lines += [
        f"OLLAMA_BASE_URL=http://localhost:11434/v1",
        f"OLLAMA_MODEL={MODEL}",
        "USE_LLM_CLASSIFIER=false",
        "MIN_RETRIEVAL_SCORE=0.01",
    ]
    (root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  Da ghi .env")


def ensure_ollama_model():
    step(5, 6, "OLLAMA: TAI MODEL AI CHAY TRONG MAY")
    if not (shutil.which("ollama") or _port_open()):
        print("  May chua co Ollama.")
        print("  -> Tai tai: https://ollama.com/download/windows  (cai xong chay lai Setup buoc nay se tu tiep)")
        print("  (Bo qua van dung duoc neu da dan GEMINI_API_KEY o buoc 4)")
        return
    for attempt in range(1, 4):
        rc = run(["ollama", "pull", MODEL]).returncode
        if rc == 0:
            run(["ollama", "list"])
            return
        print(f"  Lan {attempt} bi mat ket noi - dang thu lai (tu resume)...")
        time.sleep(5)
    print("  !!! Chua tai duoc model. Chay lai file TaiOllamaModel.bat sau khi mang on dinh.")


def _port_open(port: int = 11434) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def shortcut_and_launch(root: Path):
    step(6, 6, "SHORTCUT DESKTOP + KHOI DONG")
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$d = [Environment]::GetFolderPath('Desktop')
$l = $ws.CreateShortcut("$d\\Rightly.lnk")
$l.TargetPath = '{root}\\Rightly.bat'
$l.WorkingDirectory = '{root}'
$l.IconLocation = "$env:SystemRoot\\System32\\SHELL32.dll,13"
$l.Save()
Write-Host ("Shortcut: " + (Test-Path "$d\\Rightly.lnk"))
"""
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", ps], check=False)


def main() -> None:
    print("=" * 54)
    print("  RIGHTLY SETUP - Tro ly phap ly Tieng Lang")
    print("  Quay trinh tu dong: chay file nay tren may MOI")
    print("=" * 54)

    if os.environ.get("SETUP_DRYRUN") == "1":
        print("[DRY-RUN] chi kiem tra luong, bo qua cac buoc nang.")
        print("(dry) python OK | (dry) venv OK | (dry) deps OK | (dry) env OK | (dry) skip ollama | (dry) skip shortcut")
        return

    # Frozen exe: giai nen runtime vao %USERPROFILE%\Rightly roi cai dat o do.
    if getattr(sys, "frozen", False):
        target = Path(os.environ.get("RIGHTLY_INSTALL_DIR", Path.home() / "Rightly"))
        marker = target / ".extracted"
        if os.environ.get("SETUP_EXTRACT_ONLY") == "1":
            extract_bundle(target)
            marker.write_text("ok", encoding="utf-8")
            print("[EXTRACT-ONLY] done")
            return
        if not marker.exists():
            extract_bundle(target)
            marker.write_text("ok", encoding="utf-8")
        else:
            print(f"  Runtime da ton tai tai {target} - dung lai.")
        os.chdir(target)

    py = ensure_python()
    venv_py, root_s = ensure_venv(py)
    root = Path(root_s)
    os.chdir(root)

    install_deps(venv_py, root)

    test_mode = os.environ.get("SETUP_TEST_MODE") == "1"

    # Nhan dien phan cung bang chinh python cua venv, hien thi ro de quay clip
    step(4, 6, "NHAN DIEN CAU HINH MAY -> CHON MODEL PHU HOP")
    det = root / "scripts" / "detect_hardware.py"
    r = run([venv_py, str(det)], capture_output=True, text=True,
            encoding="utf-8", errors="replace")
    info = {}
    try:
        start = r.stdout.index("{")
        info = json.loads(r.stdout[start:])
    except Exception:
        pass
    reco = info.get("recommendation", {})
    print("  May cua ban:")
    print(f"    - CPU       : {info.get('cpu_cores', '?')} lo")
    print(f"    - RAM       : {info.get('ram_gb', '?')} GB")
    print(f"    - GPU VRAM  : {info.get('gpu_vram_gb', '?')} GB")
    print(f"    - Ollama    : {'co' if info.get('ollama') else 'chua co'}")
    chosen = reco.get("ollama_model") or MODEL
    print(f"  => Chon model AI local : {chosen}")
    print(f"     Ly do              : {reco.get('note', 'pho hop cau hinh may')}")

    gem = ""
    try:
        gem = input("  (TUY CHON) Dan GEMINI_API_KEY de tra loi chinh xac hon qua cloud [Enter = bo qua]: ").strip()
    except EOFError:
        pass

    lines = [
        f"# Rightly .env - sinh boi Setup ngay {time.strftime('%Y-%m-%d')}",
        "APP_MODE=local",
        "ASR_BACKEND=whisper",
        "RETRIEVAL_BACKEND=bm25",
        "TTS_BACKEND=mock",
    ]
    if gem:
        lines += ["LLM_BACKEND=gemini", "LLM_FALLBACK_BACKEND=local",
                  f"GEMINI_API_KEY={gem}", "GEMINI_MODEL=gemini-2.5-flash",
                  "GEMINI_THINKING_BUDGET=512"]
    else:
        lines += ["LLM_BACKEND=local"]
    lines += [
        "OLLAMA_BASE_URL=http://localhost:11434/v1",
        f"OLLAMA_MODEL={chosen}",
        "USE_LLM_CLASSIFIER=false",
        "MIN_RETRIEVAL_SCORE=0.01",
    ]
    (root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  Da ghi .env (model=" + chosen + ")")

    if test_mode:
        print("  [TEST MODE] bo qua Ollama + shortcut + launch")
        return
    ensure_ollama_model()
    shortcut_and_launch(root)

    print("\n" + "=" * 54)
    print("  CAI DAT XONG! Dang khoi dong Rightly...")
    print("=" * 54)
    time.sleep(2)
    bat = root / "Rightly.bat"
    if bat.exists():
        os.system(f'start "" "{bat}"')


if __name__ == "__main__":
    main()
