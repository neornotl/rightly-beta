@echo off
chcp 65001 >nul
title Cai Dat Rightly - Tro Ly Phap Ly Tieng Lang
echo.
echo  ============================================
echo    CAI DAT RIGHTLY (Tieng Lang) - mot lan la xong
echo    Chi chay file nay MOT LAN thoi nhe!
echo  ============================================
echo.

cd /d "%~dp0"

echo [1/7] Kiem tra Python...
where python >nul 2>nul
if not errorlevel 1 python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 goto :have_python
where py >nul 2>nul
if not errorlevel 1 py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 goto :have_py

echo.
echo  May ban CHUA CO Python.
echo  Dang tu dong cai Python qua Microsoft Store / winget...
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if %errorlevel%==0 (
    echo Da cai xong Python! Dang tu dong nap lai duong dan de tiep tuc...
    rem winget does not always refresh PATH inside the current cmd window.
    for /d %%P in ("%LocalAppData%\Programs\Python\Python*") do if exist "%%~fP\python.exe" set "PATH=%%~fP;%%~fP\Scripts;%PATH%"
    where python >nul 2>nul
    if not errorlevel 1 goto :have_python
    where py >nul 2>nul
    if not errorlevel 1 goto :have_py
    echo Python da cai nhung PATH chua cap nhat kip. Hay dong cua so nay va bam lai mot lan.
) else (
    echo Khong tu dong cai duoc. Hay mo link nay va tai Python 3.12:
    echo     https://www.python.org/downloads/
    echo Sau khi cai xong, NHO tick "Add Python to PATH" roi chay lai file nay.
)
pause
exit /b 1

:have_py
set "PYCMD=py"
goto :venv

:have_python
set "PYCMD=python"

:venv
echo [2/7] Tao khoi phan mem rieng (.venv)...
if not exist ".venv" %PYCMD% -m venv .venv
if errorlevel 1 (
    echo Loi tao venv! Thu lai bang quyen Administrator hoac kiem tra dung dia trong.
    pause & exit /b 1
)

echo [3/7] Cai cac goi can thiet (lan dau mat 3-5 phut, xin cho a)...
call ".venv\Scripts\activate.bat"
python -m pip install --no-cache-dir --upgrade pip -q
pip install --no-cache-dir -r requirements-deploy.txt -q
pip install --no-cache-dir pypdf python-docx -q
if errorlevel 1 (
    echo Co loi khi cai goi. Kiem tra internet roi chay lai file nay.
    pause & exit /b 1
)

echo [4/7] Nhan dien cau hinh may tinh de chon AI phu hop...
python scripts\detect_hardware.py
if exist ".env" (
    echo    File cau hinh .env da co - giu nguyen.
) else (
    echo    Chua co .env - se dung che do mac dinh (AI local qua Ollama).
)
set "DETECTED_MODEL="
if exist ".rightly-hardware.env" for /f "usebackq tokens=1,* delims==" %%A in (".rightly-hardware.env") do if /i "%%A"=="OLLAMA_MODEL" set "DETECTED_MODEL=%%B"
if not defined DETECTED_MODEL set "DETECTED_MODEL=qwen2.5:7b-instruct-q4_K_M"

echo [5/7] Tai va kiem tra tron bo stack offline (LLM + ASR + Piper TTS)...
echo    Can internet o buoc nay; sau khi xong Rightly khong can mang.
python scripts\bootstrap_offline.py --deps --ollama --asr --piper --skip-torch --env offline --force-env --model "%DETECTED_MODEL%"
if errorlevel 1 (
    echo    Loi tai model offline. Setup CHUA hoan tat; chay lai file nay de tiep tuc.
    pause & exit /b 1
)
python scripts\preflight_offline.py
if errorlevel 1 (
    echo    Offline preflight that bai. Setup CHUA hoan tat; chay lai de sua.
    pause & exit /b 1
)

echo [6/7] Dong goi ung dung Rightly.exe...
python scripts\build_rightly_exe.py
if errorlevel 1 (
    echo    Khong tao duoc Rightly.exe. Setup CHUA hoan tat.
    pause & exit /b 1
)

echo [7/7] Tao icon Rightly ngoai man hinh chinh...
powershell -NoProfile -Command ^
 "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Rightly.lnk'); $lnk.TargetPath = '%~dp0dist\Rightly.exe'; $lnk.WorkingDirectory = '%~dp0'; $lnk.IconLocation = '%~dp0assets\rightly.ico,0'; $lnk.Save()"
echo    Da tao icon "Rightly.exe" ngoai Desktop!

echo.
echo  ============================================
echo    CAI DAT HOAN TAT!
echo    Tu gio chi can nhan doi icon "Rightly"
echo    tren Desktop la dung duoc ngay.
echo  ============================================
echo.
echo Dang mo Rightly lan dau...
start "Rightly" "%~dp0dist\Rightly.exe"
exit /b 0
