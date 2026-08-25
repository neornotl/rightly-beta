"""Build the single-file native Rightly.exe launcher."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
ICON = ROOT / "assets" / "rightly.ico"


def main() -> int:
    entry = ROOT / "rightly_desktop.py"
    if not entry.exists():
        print(f"Missing desktop entrypoint: {entry}")
        return 1
    separator = os.pathsep
    if not ICON.exists():
        print(f"Missing app icon: {ICON}")
        return 1
    builder = ROOT / ".venv" / "Scripts" / "python.exe"
    if not builder.exists():
        builder = Path(sys.executable)
    command = [
        str(builder),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "Rightly",
        "--icon",
        str(ICON),
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build" / "rightly"),
        "--specpath",
        str(ROOT / "build"),
        "--add-data",
        f"{ROOT / 'web'}{separator}web",
        "--collect-all",
        "webview",
        str(entry),
    ]
    print("Building Rightly.exe ...")
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode != 0 or not (DIST / "Rightly.exe").exists():
        print("Rightly.exe build failed")
        return completed.returncode or 1
    print(f"Ready: {DIST / 'Rightly.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
