"""Native Rightly desktop shell.

The executable is built after the one-time installer has populated the local
venv and models.  It starts the loopback FastAPI server, waits for /health,
then hosts the existing web UI in a native WebView window.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def _root() -> Path:
    # The desktop shortcut sets WorkingDirectory to the project root.  Keep an
    # environment override for QA and portable copies of the generated app.
    explicit = os.environ.get("RIGHTLY_ROOT")
    candidates = [Path(explicit)] if explicit else []
    candidates.extend([Path.cwd(), Path(sys.executable).resolve().parent])
    exe_parent = Path(sys.executable).resolve().parent
    candidates.extend([exe_parent.parent, exe_parent.parent.parent])
    for candidate in candidates:
        if candidate and (candidate / ".venv" / "Scripts" / "python.exe").exists():
            return candidate.resolve()
    return Path(explicit or Path.cwd()).resolve()


def _health(port: int = 8010) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _error(message: str) -> None:
    try:
        import tkinter.messagebox as messagebox

        messagebox.showerror("Rightly chưa sẵn sàng", message)
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    root = _root()
    python = root / ".venv" / "Scripts" / "python.exe"
    server_script = root / "webhook_server.py"
    if not python.exists() or not server_script.exists():
        _error("Chưa tìm thấy bộ cài Rightly. Hãy chạy CaiDat-Rightly.bat trước.")
        return 1

    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_file = (logs / "rightly-app.log").open("a", encoding="utf-8")
    # Reuse a healthy instance if the user double-clicks the shortcut twice.
    # This prevents a second uvicorn process from fighting for port 8010.
    server = None
    if not _health():
        server = subprocess.Popen(
            [str(python), str(server_script)],
            cwd=str(root),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    try:
        ready = False
        for _ in range(90):
            if _health():
                ready = True
                break
            time.sleep(1)
        if not ready:
            _error("Rightly không khởi động được. Xem logs\\rightly-app.log để biết nguyên nhân.")
            return 1
        try:
            import webview

            webview.create_window(
                "Rightly – Trợ lý pháp luật",
                "http://localhost:8010",
                width=1280,
                height=860,
                min_size=(960, 640),
                text_select=True,
            )
            webview.start(debug=False)
        except Exception as exc:
            # WebView2 may be unavailable on an older Windows image.  Keep the
            # service usable through the browser instead of showing localhost
            # before it is ready.
            webbrowser.open("http://localhost:8010")
            _error(f"Không mở được cửa sổ app native ({exc}). Rightly đã mở bằng trình duyệt.")
            while server is not None and server.poll() is None:
                time.sleep(1)
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
        log_file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
