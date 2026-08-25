# -*- coding: utf-8 -*-
"""Rightly-Setup: one-file installer for the local Rightly app.

The installer extracts a private runtime folder under ``%LOCALAPPDATA%`` or
``%USERPROFILE%`` and then runs the same offline bootstrap/preflight used by
the development installer.  It only creates a Desktop shortcut after Python,
dependencies, Ollama, ASR, Piper, the local model and the health/chat smoke
test are ready.
"""

from __future__ import annotations

import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

MODEL = "qwen2.5:3b-instruct-q4_K_M"
APP_EXE_NAME = "Rightly.exe"
# Bump whenever bundled runtime scripts change. Existing installs then receive
# the fixed installer/bootstrap code on the next run without rebuilding venv or
# redownloading already-installed models.
INSTALLER_MARKER = "rightly-installer-v17"
INSTALL_RETRIES = 6
INSTALL_RETRY_DELAY_S = 8

_UI = None
_INSTANCE_LOCK_HANDLE = None

def _prepare_output_streams():
    """PyInstaller windowed builds have no console streams."""
    if getattr(sys, "stdout", None) is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if getattr(sys, "stderr", None) is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    try:  # exe console mặc định cp1252 -> ép UTF-8 để không crash tiếng Việt
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


_prepare_output_streams()


class _TeeOutput:
    """Keep the legacy terminal log while mirroring it into the installer UI."""

    def __init__(self, original, ui):
        self.original = original
        self.ui = ui

    def write(self, value):
        if self.original:
            try:
                self.original.write(value)
                self.original.flush()
            except Exception:
                pass
        if value and value.strip():
            self.ui.log(value.strip())

    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass


class InstallerUI:
    """Small dependency-free installer window.

    Tkinter ships with the Windows Python runtime and is bundled by PyInstaller,
    so the one-file setup does not need a separate UI asset or executable.
    """

    def __init__(self):
        import tkinter as tk
        from tkinter import messagebox, scrolledtext, ttk

        self.tk = tk
        self.messagebox = messagebox
        self.queue = queue.Queue()
        self.result = 1
        self.current_step = 0
        self.total_steps = 6
        self.root = tk.Tk()
        self.root.title("Rightly – Cài đặt trợ lý pháp luật")
        self.root.geometry("760x560")
        self.root.resizable(False, False)
        icon = Path(getattr(sys, "_MEIPASS", ".")) / "assets" / "rightly.ico"
        if icon.exists():
            try:
                self.root.iconbitmap(str(icon))
            except Exception:
                pass

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground="#17324d")
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground="#627386")
        style.configure("Step.TLabel", font=("Segoe UI", 11, "bold"), foreground="#17324d")
        style.configure("Status.TLabel", font=("Segoe UI", 10), foreground="#627386")
        style.configure("Accent.Horizontal.TProgressbar", troughcolor="#e7edf2", background="#2d9d8b")
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), foreground="#ffffff", background="#237a70")

        outer = ttk.Frame(self.root, padding=(28, 24, 28, 20))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="Rightly", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Cài một lần, dùng trợ lý pháp luật ngay trên máy của bạn",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        self.stage_var = tk.StringVar(value="Đang chuẩn bị bộ cài…")
        self.percent_var = tk.StringVar(value="0%")
        stage_row = ttk.Frame(outer)
        stage_row.pack(fill="x", pady=(24, 5))
        ttk.Label(stage_row, textvariable=self.stage_var, style="Step.TLabel").pack(side="left")
        ttk.Label(stage_row, textvariable=self.percent_var, style="Status.TLabel").pack(side="right")
        self.progress = ttk.Progressbar(
            outer, orient="horizontal", mode="determinate", maximum=100,
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", ipady=3)

        self.status_var = tk.StringVar(value="Không đóng cửa sổ trong lúc đang cài đặt.")
        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w", pady=(8, 10))

        log_frame = ttk.LabelFrame(outer, text="Nhật ký cài đặt", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=20,
            width=88,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
            background="#fbfcfd",
            foreground="#233746",
            relief="flat",
        )
        self.log_text.pack(fill="both", expand=True)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(14, 0))
        self.help_var = tk.StringVar(value="Bộ cài sẽ tự tiếp tục nếu mạng chập chờn.")
        ttk.Label(footer, textvariable=self.help_var, style="Status.TLabel").pack(side="left")
        self.close_button = ttk.Button(footer, text="Đang cài…", state="disabled", command=self.root.destroy)
        self.close_button.pack(side="right")
        self.root.protocol("WM_DELETE_WINDOW", self._ignore_close)
        self.root.after(100, self._drain)

    def _ignore_close(self):
        self.status_var.set("Đang cài đặt, vui lòng chờ bước kiểm tra hoàn tất.")

    def log(self, message):
        self.queue.put(("log", str(message)))

    def set_step(self, n, total, title):
        self.queue.put(("step", n, total, title))

    def finish(self, result, error=None):
        self.queue.put(("finish", result, error))

    def _drain(self):
        try:
            while True:
                event = self.queue.get_nowait()
                kind = event[0]
                if kind == "log":
                    self.log_text.configure(state="normal")
                    text = event[1].replace("\r", "\n")
                    for line in text.splitlines():
                        if line.strip():
                            clean = line[:500]
                            self.log_text.insert("end", clean + "\n")
                            percent = re.search(r"(?<!\d)(\d{1,3})\s*%", clean)
                            if percent and self.current_step:
                                local = max(0, min(100, int(percent.group(1))))
                                value = round(((self.current_step - 1) + local / 100) * 100 / self.total_steps)
                                self.progress.configure(value=value)
                                self.percent_var.set(f"{value}%")
                    # Keep the window responsive even when pip emits thousands of lines.
                    line_count = int(self.log_text.index("end-1c").split(".")[0])
                    if line_count > 900:
                        self.log_text.delete("1.0", "200.0")
                    self.log_text.see("end")
                    self.log_text.configure(state="disabled")
                elif kind == "step":
                    _, n, total, title = event
                    self.current_step = n
                    self.total_steps = total
                    value = max(0, min(100, round((n - 1) * 100 / max(1, total))))
                    self.progress.configure(value=value)
                    self.percent_var.set(f"{value}%")
                    self.stage_var.set(title.title())
                    self.status_var.set(f"Bước {n}/{total} · Đang xử lý…")
                elif kind == "finish":
                    _, result, error = event
                    self.result = int(result)
                    if self.result == 0:
                        self.progress.configure(value=100)
                        self.percent_var.set("100%")
                        self.stage_var.set("Cài đặt hoàn tất")
                        self.status_var.set("Rightly đã sẵn sàng. Bạn có thể bắt đầu sử dụng.")
                        self.help_var.set("Shortcut Rightly đã được tạo trên màn hình Desktop.")
                        self.close_button.configure(text="Đóng", state="normal")
                    else:
                        self.stage_var.set("Cài đặt chưa hoàn tất")
                        self.status_var.set(error or "Có lỗi xảy ra; xem nhật ký để biết bước cần chạy lại.")
                        self.help_var.set("Bạn có thể chạy lại đúng file installer để tiếp tục từ cache.")
                        self.close_button.configure(text="Đóng", state="normal")
                    self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _worker(self):
        global _UI
        original_out, original_err = sys.stdout, sys.stderr
        sys.stdout = _TeeOutput(original_out, self)
        sys.stderr = _TeeOutput(original_err, self)
        try:
            result = main()
            self.finish(result, None if result == 0 else "Cài đặt chưa hoàn tất. Hãy xem nhật ký và chạy lại file này.")
        except Exception as exc:
            self.log(traceback.format_exc())
            self.finish(1, f"Lỗi: {exc}")
        finally:
            sys.stdout, sys.stderr = original_out, original_err
            _UI = None

    def run(self):
        threading.Thread(target=self._worker, name="rightly-installer", daemon=False).start()
        self.root.mainloop()
        return self.result


def run(cmd, **kw):
    """Run a command and stream its output into the GUI when available."""
    normalized = [str(c) for c in cmd]
    print(f"  $ {' '.join(normalized)}", flush=True)
    if _UI is None or kw.get("capture_output") or kw.get("stdout") is not None:
        return subprocess.run(normalized, **kw)

    check = bool(kw.pop("check", False))
    popen_kw = dict(kw)
    popen_kw["stdout"] = subprocess.PIPE
    popen_kw["stderr"] = subprocess.STDOUT
    popen_kw["text"] = False
    if os.name == "nt" and "creationflags" not in popen_kw:
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(normalized, **popen_kw)
    assert process.stdout is not None
    # Read from a helper thread.  A direct read(2048) can wait forever when a
    # child emits a short status line and then spends several minutes loading a
    # model; the installer UI would look frozen even though the child is alive.
    output_queue = queue.Queue()

    def _reader():
        while True:
            chunk = process.stdout.read(2048)
            if not chunk:
                break
            output_queue.put(chunk)

    reader = threading.Thread(target=_reader, name="rightly-installer-output", daemon=True)
    reader.start()
    pending = ""
    while reader.is_alive() or not output_queue.empty():
        try:
            chunk = output_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        pending += chunk.decode("utf-8", errors="replace")
        parts = pending.replace("\r", "\n").split("\n")
        pending = parts.pop() if parts else ""
        for line in parts:
            if line.strip():
                print(line.strip(), flush=True)
    reader.join(timeout=2)
    if pending.strip():
        print(pending.strip(), flush=True)
    return_code = process.wait()
    completed = subprocess.CompletedProcess(normalized, return_code)
    if check and return_code:
        raise subprocess.CalledProcessError(return_code, normalized)
    return completed


def _parse_detection_output(result) -> dict:
    """Parse the detector's JSON even when it prints a human-readable footer."""
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"detect_hardware.py failed (exit {result.returncode}): {detail[-800:]}")
    output = result.stdout or ""
    start = output.find("{")
    if start < 0:
        raise RuntimeError("detect_hardware.py did not return a JSON hardware report")
    try:
        info, _ = json.JSONDecoder().raw_decode(output[start:])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid hardware report: {exc}") from exc
    required = ("cpu_cores", "ram_gb", "gpu_vram_gb", "ollama", "recommendation")
    missing = [key for key in required if key not in info]
    if missing:
        raise RuntimeError("hardware report missing: " + ", ".join(missing))
    return info


def run_with_retries(cmd, label):
    """Retry network-backed installer steps without restarting the setup."""
    for attempt in range(1, INSTALL_RETRIES + 1):
        result = run(cmd)
        if result.returncode == 0:
            return result
        if attempt >= INSTALL_RETRIES:
            break
        delay = min(120, INSTALL_RETRY_DELAY_S * (2 ** (attempt - 1)))
        print(
            f"  Mạng chưa ổn định khi {label}; giữ cache và thử lại sau "
            f"{delay}s (lần {attempt}/{INSTALL_RETRIES - 1})...",
            flush=True,
        )
        time.sleep(delay)
    raise RuntimeError(
        f"Không cài được {label} sau {INSTALL_RETRIES} lần thử. "
        "Hãy giữ nguyên thư mục Rightly và chạy lại để tiếp tục."
    )


def pause_for_user():
    """Console pause for source checkout; never block a windowed installer."""
    if _UI is not None:
        return
    try:
        input("Nhấn Enter để thoát...")
    except (EOFError, KeyboardInterrupt):
        pass


def acquire_instance_lock() -> bool:
    """Allow only one normal installer session at a time.

    The handle remains open for the lifetime of this process, so Windows
    releases the lock automatically even after a crash or forced close.
    """
    global _INSTANCE_LOCK_HANDLE
    if os.name != "nt":
        return True
    try:
        import msvcrt

        lock_path = Path(os.environ.get("TEMP", str(Path.home()))) / "Rightly-Setup.lock"
        _INSTANCE_LOCK_HANDLE = open(lock_path, "a+b")
        _INSTANCE_LOCK_HANDLE.seek(0)
        _INSTANCE_LOCK_HANDLE.write(b"0")
        _INSTANCE_LOCK_HANDLE.flush()
        _INSTANCE_LOCK_HANDLE.seek(0)
        msvcrt.locking(_INSTANCE_LOCK_HANDLE.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except (OSError, IOError):
        try:
            if _INSTANCE_LOCK_HANDLE:
                _INSTANCE_LOCK_HANDLE.close()
        finally:
            _INSTANCE_LOCK_HANDLE = None
        return False


def step(n, total, title):
    bar = "=" * 52
    print(f"\n[{n}/{total}] {title}\n{bar}", flush=True)
    if _UI is not None:
        _UI.set_step(n, total, title)


BUNDLE_ITEMS = [
    "app", "web", "data", "scripts", "assets",
    "webhook_server.py", "requirements.txt", "requirements-optional.txt",
    "requirements-deploy.txt",
    "Rightly.bat", "TaiOllamaModel.bat", "README-NGUOI-DUNG.txt",
    "LICENSE", ".env.example",
]


def install_dir() -> Path:
    explicit = os.environ.get("RIGHTLY_INSTALL_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home()
    return (base / "Rightly").resolve()


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
    # The app launcher is prebuilt before Rightly-Setup.exe is created.  It
    # must be copied as a top-level file so the user can launch it directly.
    launcher = src / "dist" / APP_EXE_NAME
    if launcher.exists():
        shutil.copy2(launcher, target / APP_EXE_NAME)
    else:
        raise RuntimeError(f"Bộ cài thiếu {APP_EXE_NAME}; hãy tạo lại bộ cài.")
    print("  Extract xong.", flush=True)


def find_python() -> str | None:
    candidates: list[str] = []
    for cand in ("python", "py"):
        if shutil.which(cand):
            candidates.append(cand)
    for env_name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env_name)
        if base:
            candidates.extend(str(path) for path in Path(base).glob("Programs/Python/Python*/python.exe"))
            candidates.extend(str(path) for path in Path(base).glob("Python*/python.exe"))
    for cand in candidates:
        try:
            check = subprocess.run(
                [cand, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            if check.returncode == 0:
                return cand
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _download_resumable(url: str, destination: Path) -> Path:
    """Download a small bootstrap installer while preserving a partial file."""
    partial = destination.with_name(destination.name + ".part")
    for attempt in range(1, INSTALL_RETRIES + 1):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            request = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(request, timeout=90) as response:
                # Some proxies ignore Range and return the whole file.
                if offset and getattr(response, "status", 206) != 206:
                    offset = 0
                mode = "ab" if offset else "wb"
                with partial.open(mode) as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            partial.replace(destination)
            return destination
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            if attempt >= INSTALL_RETRIES:
                raise RuntimeError(f"Không tải được Python từ python.org: {exc}") from exc
            delay = min(60, INSTALL_RETRY_DELAY_S * attempt)
            print(f"  Mạng chập chờn khi tải Python; tiếp tục sau {delay}s ({attempt}/{INSTALL_RETRIES - 1})…")
            time.sleep(delay)
    raise RuntimeError("Không tải được Python.")


def check_machine_requirements() -> None:
    """Fail early with an actionable message instead of half-installing."""
    if os.name != "nt" or "64" not in platform.machine():
        raise RuntimeError("Rightly Setup hiện yêu cầu Windows 10/11 bản 64-bit.")
    usage = shutil.disk_usage(install_dir().anchor or str(Path.home()))
    free_gb = usage.free / (1024 ** 3)
    if free_gb < 25:
        raise RuntimeError(f"Ổ đĩa chỉ còn {free_gb:.1f} GB; cần tối thiểu 25 GB để tải model và thư viện.")


def ensure_python() -> str:
    step(1, 6, "KIEM TRA PYTHON")
    check_machine_requirements()
    py = find_python()
    if py:
        print(f"  Da co Python ({py})")
        return py
    print("  May chua co Python -> tu dong cai qua winget...")
    winget_ok = False
    if shutil.which("winget"):
        winget_ok = run(["winget", "install", "-e", "--id", "Python.Python.3.12",
                         "--accept-source-agreements", "--accept-package-agreements"]).returncode == 0
    if not winget_ok:
        # Windows 10 machines sometimes do not have App Installer/winget.
        # Keep the one-file promise by falling back to the official installer.
        print("  Winget không khả dụng -> tải Python chính thức từ python.org…")
        cache = Path(os.environ.get("TEMP", str(Path.home()))) / "Rightly" / "python-3.12.10-amd64.exe"
        cache.parent.mkdir(parents=True, exist_ok=True)
        _download_resumable(
            os.environ.get(
                "RIGHTLY_PYTHON_URL",
                "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe",
            ),
            cache,
        )
        installer = run([str(cache), "/quiet", "InstallAllUsers=0", "PrependPath=1",
                          "Include_launcher=1", "Include_test=0"])
        if installer.returncode != 0:
            raise RuntimeError(f"Trình cài Python kết thúc với mã {installer.returncode}.")
    # refresh PATH from registry (rough): rely on restart message if still missing
    py = find_python()
    if not py:
        raise RuntimeError("Đã cài Python nhưng chưa tìm thấy python.exe. Hãy chạy lại file installer.")
    return py


def ensure_venv(py: str) -> tuple[str, str]:
    step(2, 6, "TAO MOI TRUONG RIENG (.venv)")
    root = Path.cwd()
    venv_py = root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python")
    if not venv_py.exists():
        run([py, "-m", "venv", ".venv"])
    if not venv_py.exists():
        raise RuntimeError("Không tạo được môi trường Python riêng (.venv).")
    print("  .venv OK:", venv_py)
    return str(venv_py), str(root)


def install_deps(venv_py: str, root: Path):
    step(3, 6, "CAI THU VIEN (lan dau ~3 phut)")
    # Modern pip refuses self-upgrades through the pip.exe shim inside a
    # venv. Always invoke it through the exact interpreter being configured.
    pip = [venv_py, "-m", "pip"]
    run_with_retries(
        [*pip, "install", "--no-cache-dir", "--upgrade", "pip", "-q"],
        "pip",
    )
    run_with_retries(
        [
            *pip,
            "install",
            "--no-cache-dir",
            "-r",
            str(root / "requirements-deploy.txt"),
            "pypdf",
            "python-docx",
            "-q",
        ],
        "thư viện Rightly",
    )


def write_env(root: Path) -> None:
    """Legacy helper retained for source checkouts; always writes offline config."""
    lines = [
        f"# Rightly .env - sinh boi Setup ngay {time.strftime('%Y-%m-%d')}",
        "APP_MODE=local",
        "ASR_BACKEND=whisper",
        "RETRIEVAL_BACKEND=bm25",
        "TTS_BACKEND=piper",
        "WHISPER_MODEL_PATH=data/models/faster-whisper-small",
        "PIPER_MODEL_PATH=data/voices/vi_VN-vais1000-medium.onnx",
        "PIPER_MODEL_PATH_EN=data/voices/en_US-lessac-medium.onnx",
        "OFFLINE_MODE=true",
        "LOCAL_MEMORY_PATH=data/private_cache/memory.sqlite3",
    ]
    lines += ["LLM_BACKEND=local"]
    lines += [
        f"OLLAMA_BASE_URL=http://localhost:11434/v1",
        f"OLLAMA_MODEL={MODEL}",
        "USE_LLM_CLASSIFIER=false",
        "MIN_RETRIEVAL_SCORE=0.01",
    ]
    (root / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  Da ghi .env")


def shortcut_and_launch(root: Path):
    step(6, 6, "SHORTCUT DESKTOP + KHOI DONG")
    app_exe = root / APP_EXE_NAME
    if not app_exe.exists():
        raise RuntimeError(f"Không tìm thấy {app_exe}")
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$d = [Environment]::GetFolderPath('Desktop')
$l = $ws.CreateShortcut("$d\\Rightly.lnk")
$l.TargetPath = '{app_exe}'
$l.WorkingDirectory = '{root}'
$l.IconLocation = '{app_exe},0'
$l.Save()
Write-Host ("Shortcut: " + (Test-Path "$d\\Rightly.lnk"))
"""
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", ps], check=False)


def main() -> int:
    print("=" * 54)
    print("  RIGHTLY SETUP - Tro ly phap ly Tieng Lang")
    print("  Quay trinh tu dong: chay file nay tren may MOI")
    print("=" * 54)

    if os.environ.get("SETUP_DRYRUN") == "1":
        print("[DRY-RUN] chi kiem tra luong, bo qua cac buoc nang.")
        print("(dry) python OK | (dry) venv OK | (dry) deps OK | (dry) env OK | (dry) skip ollama | (dry) skip shortcut")
        return 0

    # Frozen exe: giải nén runtime vào thư mục riêng của người dùng.
    if getattr(sys, "frozen", False):
        target = install_dir()
        marker = target / ".extracted"
        if os.environ.get("SETUP_EXTRACT_ONLY") == "1":
            extract_bundle(target)
            marker.write_text(INSTALLER_MARKER, encoding="utf-8")
            print("[EXTRACT-ONLY] done")
            return 0
        marker_value = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
        if marker_value != INSTALLER_MARKER or not (target / APP_EXE_NAME).exists():
            extract_bundle(target)
            marker.write_text(INSTALLER_MARKER, encoding="utf-8")
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
    try:
        info = _parse_detection_output(r)
    except RuntimeError as exc:
        print(f"!!! Không nhận diện được phần cứng thật: {exc}")
        if r.stdout:
            print(r.stdout[-1200:])
        if r.stderr:
            print(r.stderr[-1200:])
        return 1
    reco = info.get("recommendation", {})
    print("  May cua ban:")
    print(f"    - CPU       : {info.get('cpu_cores', '?')} lo")
    print(f"    - RAM       : {info.get('ram_gb', '?')} GB")
    print(f"    - GPU VRAM  : {info.get('gpu_vram_gb', '?')} GB")
    ollama_state = "co" if info.get("ollama") else "chua co"
    print(f"    - Ollama    : {ollama_state}")
    if info.get("ollama_path"):
        print(f"      Duong dan: {info['ollama_path']}")
    chosen = str(reco.get("ollama_model") or "").strip()
    if not chosen:
        print("!!! Không có model local phù hợp với cấu hình máy; bộ cài dừng để tránh chọn sai.")
        return 1
    print(f"  => Chon model AI local : {chosen}")
    print(f"     Ly do              : {reco.get('note', 'pho hop cau hinh may')}")

    if test_mode:
        print("  [TEST MODE] bo qua Ollama + shortcut + launch")
        return 0
    step(5, 6, "TAI VA KIEM TRA STACK OFFLINE (LLM + ASR + PIPER)")
    bootstrap = root / "scripts" / "bootstrap_offline.py"
    bootstrap_cmd = [
        venv_py, str(bootstrap), "--deps", "--ollama", "--asr", "--piper",
        "--skip-torch", "--env", "offline", "--force-env", "--model", chosen,
    ]
    if run(bootstrap_cmd, cwd=root).returncode != 0:
        print("!!! Offline bootstrap thất bại. Bộ cài chưa hoàn tất.")
        return 1

    preflight = root / "scripts" / "preflight_offline.py"
    if run([venv_py, str(preflight)], cwd=root).returncode != 0:
        print("!!! Offline preflight thất bại. Bộ cài chưa hoàn tất.")
        return 1

    shortcut_and_launch(root)

    print("\n" + "=" * 54)
    print("  CAI DAT XONG! Dang khoi dong Rightly...")
    print("=" * 54)
    time.sleep(2)
    app_exe = root / APP_EXE_NAME
    subprocess.Popen([str(app_exe)], cwd=str(root), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def launch() -> int:
    """Use the GUI for normal double-click installs; keep CLI modes for tests."""
    global _UI
    if any(os.environ.get(name) == "1" for name in ("SETUP_DRYRUN", "SETUP_TEST_MODE", "SETUP_EXTRACT_ONLY")):
        return main()
    if not acquire_instance_lock():
        try:
            from tkinter import messagebox

            messagebox.showinfo(
                "Rightly Setup",
                "Bộ cài Rightly đang chạy ở một cửa sổ khác. "
                "Hãy đóng cửa sổ đó hoặc chờ cài xong rồi thử lại.",
            )
        except Exception:
            pass
        return 1
    try:
        _UI = InstallerUI()
    except Exception as exc:
        # A source checkout may still be run from a minimal Python without Tk.
        print(f"Không mở được giao diện installer ({exc}); chuyển sang chế độ chữ.")
        _UI = None
        return main()
    return _UI.run()


if __name__ == "__main__":
    raise SystemExit(launch())
