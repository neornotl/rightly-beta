@echo off
REM Rightly - ONE-CLICK offline bootstrap for the demo machine (Windows).
REM Double-click this file AFTER copying the whole repo to the demo PC.
REM It downloads (once): python deps, Ollama + qwen2.5:7b-instruct-q4_k_m, PhoWhisper,
REM embedding model + caches. Then the demo runs 100% offline.

setlocal
cd /d "%~dp0\.."

echo.
echo === Rightly offline bootstrap (one-time, needs internet) ===
echo.

if not exist ".venv" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: python not found on PATH. Install Python 3.10+ from python.org first.
        pause
        exit /b 1
    )
)

echo [2/4] Installing python dependencies (differs from cloud deploy)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-optional.txt
".venv\Scripts\python.exe" -m pip install torch sentence-transformers transformers av

echo [3/4] Downloading models + building embedding caches...
".venv\Scripts\python.exe" scripts\bootstrap_offline.py --all --skip-torch

if errorlevel 1 (
    echo.
    echo Bootstrap FAILED - see messages above.
    pause
    exit /b 1
)

echo [4/4] Verifying...
".venv\Scripts\python.exe" scripts\check_local_llm.py

echo.
echo DONE. For the one-click local pilot, double-click:
echo   scripts\run_local_pilot.bat
echo.
pause
