@echo off
rem ============================================================
rem  Rightly - one-click offline launcher (Windows)
rem  Double-click this file. Everything installs and starts
rem  automatically, then the browser opens http://localhost:8010
rem ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo  ==========================================
echo   Rightly - khoi dong 1 lan (offline)
echo  ==========================================
echo.

rem ---------- 1. Find Python ----------
set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
  echo [LOI] Khong tim thay Python. Cai Python 3.10+ roi chay lai.
  echo       https://www.python.org/downloads/  (tick "Add to PATH")
  pause
  exit /b 1
)

rem ---------- 2. Create virtual env ----------
if not exist ".venv" (
  echo [1/5] Tao moi truong ao .venv ...
  python -m venv .venv
  if errorlevel 1 ( echo [LOI] Khong tao duoc .venv & pause & exit /b 1 )
)
set "PIP=.venv\Scripts\pip.exe"
set "PYV=.venv\Scripts\python.exe"
if not exist "%PYV%" (
  echo [LOI] Thieu %PYV% & pause & exit /b 1
)

rem ---------- 3. Install dependencies ----------
echo [2/5] Cai dat thu vien (lan dau co the lau) ...
"%PIP%" install -q --disable-pip-version-check -r requirements-deploy.txt
if errorlevel 1 ( echo [LOI] Cai dat thu vien that bai. Xem lai ket noi mang. & pause & exit /b 1 )

rem ---------- 4. Prepare .env (local/offline defaults) ----------
if not exist ".env" (
  echo [3/5] Tao file cau hinh .env mac dinh offline ...
  copy /y ".env.example" ".env" >nul
)

rem ---------- 4b. Auto-detect hardware and pick fitting models ----------
echo       Do cau hinh may (RAM/CPU/GPU/disk) va chon model phu hop ...
"%PYV%" scripts\detect_hardware.py --write .env
if errorlevel 1 (
  echo [WARN] Khong the tu chon model; giu cau hinh mac dinh.
)

rem ---------- 5. Ensure Ollama + model (local LLM) ----------
set "LLM_BACKEND="
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
  if /i "%%A"=="LLM_BACKEND" set "LLM_BACKEND=%%B"
)
set "OLLAMA_MODEL="
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
  if /i "%%A"=="OLLAMA_MODEL" set "OLLAMA_MODEL=%%B"
)
if /i "%LLM_BACKEND%"=="local" (
  where ollama >nul 2>nul
  if errorlevel 1 (
    echo [LOI] LLM_BACKEND=local nhung chua cai Ollama.
    echo       Cai tu https://ollama.com/download , roi chay lai.
    pause
    exit /b 1
  )
  echo [4/5] Kiem tra model Ollama: %OLLAMA_MODEL% ...
  ollama list | findstr /i "%OLLAMA_MODEL%" >nul
  if errorlevel 1 (
    echo       Dang tai model %OLLAMA_MODEL% (mot lan, co the lau) ...
    ollama pull "%OLLAMA_MODEL%"
    if errorlevel 1 ( echo [LOI] Tai model that bai. & pause & exit /b 1 )
  )
  rem Make sure the Ollama service is running
  tasklist | findstr /i "ollama" >nul || start "" ollama serve
) else (
  echo [4/5] Bo qua Ollama (LLM_BACKEND=%LLM_BACKEND%).
)

rem ---------- 6. Start server + open browser ----------
echo [5/5] Khoi dong web tai http://localhost:8010 ...
set "PORT=8010"
start "" /b "%PYV%" webhook_server.py
timeout /t 3 /nobreak >nul
start "" "http://localhost:8010"

echo.
echo  Dang chay. Tat cua so nay de dung.
echo  Mo lai http://localhost:8010 neu trinh duyet khong tu mo.
echo.
pause
endlocal