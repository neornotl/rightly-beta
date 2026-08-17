@echo off
REM Rightly - one-click local pilot launcher.
REM Double-click this file after offline_setup.bat has completed.

setlocal
cd /d "%~dp0\.."

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set "APP_MODE=local"
set "ASR_BACKEND=phowhisper"
set "RETRIEVAL_BACKEND=hybrid"
set "LLM_BACKEND=local"
set "LLM_FALLBACK_BACKEND="
set "TTS_BACKEND=mock"
set "SAVE_TRANSCRIPTS=false"
set "DELETE_RAW_AUDIO_AFTER_SESSION=true"
set "PII_SCRUB_OUTBOUND=true"
set "LOCAL_PILOT=true"

echo.
echo === Rightly local pilot ===
echo [1/4] Checking Ollama...
curl --silent --fail http://127.0.0.1:11434/api/tags >nul 2>&1
if errorlevel 1 (
    where ollama >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Ollama not found. Run scripts\offline_setup.bat first.
        pause
        exit /b 1
    )
    echo Starting Ollama...
    start "Rightly Ollama" /min ollama serve
    timeout /t 3 /nobreak >nul
)

echo [2/4] Checking local model...
%PYTHON% scripts\check_local_llm.py
if errorlevel 1 (
    echo ERROR: local model is not ready. Pull/configure it before the pilot.
    pause
    exit /b 1
)

echo [3/4] Starting app. Benchmark and runtime manifest run automatically.
echo [4/4] Pilot logs are written automatically under logs\ and results\.
echo Close this window to stop the local pilot.
echo.
%PYTHON% -m streamlit run app\ui.py --server.headless true

endlocal
