@echo off
chcp 65001 >nul
title Cai Dat Rightly - Tro Ly Phap Ly Tieng Lang
echo.
echo  ============================================
echo    CAI DAT RIGHTLY (Tieng Lang) - buoc 1/1
echo    Chi chay file nay MOT LAN thoi nhe!
echo  ============================================
echo.

cd /d "%~dp0"

echo [1/6] Kiem tra Python...
where python >nul 2>nul
if %errorlevel%==0 goto :have_python
where py >nul 2>nul
if %errorlevel%==0 goto :have_py

echo.
echo  May ban CHUA CO Python.
echo  Dang tu dong cai Python qua Microsoft Store / winget...
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if %errorlevel%==0 (
    echo Da cai xong Python! Hay DONG cua so nay va CHAY LAI file CaiDat-Rightly.bat nhe.
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
echo [2/6] Tao khoi phan mem rieng (.venv)...
if not exist ".venv" %PYCMD% -m venv .venv
if errorlevel 1 (
    echo Loi tao venv! Thu lai bang quyen Administrator hoac kiem tra dung dia trong.
    pause & exit /b 1
)

echo [3/6] Cai cac goi can thiet (lan dau mat 3-5 phut, xin cho a)...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip -q
pip install -r requirements-deploy.txt -q
pip install pypdf python-docx -q
if errorlevel 1 (
    echo Co loi khi cai goi. Kiem tra internet roi chay lai file nay.
    pause & exit /b 1
)

echo [4/6] Nhan dien cau hinh may tinh de chon AI phu hop...
python scripts\detect_hardware.py
if exist ".env" (
    echo    File cau hinh .env da co - giu nguyen.
) else if exist ".env.local" (
    copy /y ".env.local" ".env" >nul
    echo    Da tao .env tu khuyen nghi phan cung.
) else (
    echo    Chua co .env - se dung che do mac dinh (AI local qua Ollama).
)

echo [5/6] Kiem tra Ollama (AI chay ngay trong may)...
where ollama >nul 2>nul
if %errorlevel%==0 goto :ollama_ok
curl -s -o nul http://localhost:11434 2>nul && goto :ollama_ok
echo    May chua co Ollama. De AI chay OFFLINE trong may:
echo      1. Tai tai: https://ollama.com/download/windows
echo      2. Cai xong, mo Ollama va chay:  ollama pull qwen2.5:3b-instruct-q4_K_M
echo    (Bo qua buoc nay van dung duoc, nhap key Gemini/Groq de dung AI cloud)
goto :shortcut

:ollama_ok
echo    Ollama OK!
for /f "tokens=*" %%m in ('python -c "import re;s=open('.env',encoding='utf-8').read();m=re.search(r'OLLAMA_MODEL=(.*)',s);print(m.group(1).strip() if m else 'qwen2.5:3b-instruct-q4_K_M')"') do set NEEDMODEL=%%m
ollama list 2>nul | findstr /c:"%NEEDMODEL%" >nul
if errorlevel 1 (
    echo    Dang tai mo hinh AI %NEEDMODEL% (chi lan dau, ~2GB)...
    ollama pull %NEEDMODEL%
)

:shortcut
echo [6/6] Tao icon Rightly ngoai man hinh chinh...
powershell -NoProfile -Command ^
 "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Rightly.lnk'); $lnk.TargetPath = '%~dp0Rightly.bat'; $lnk.WorkingDirectory = '%~dp0'; $lnk.IconLocation = '%SystemRoot%\System32\SHELL32.dll,13'; $lnk.Save()"
echo    Da tao icon "Rightly" ngoai Desktop!

echo.
echo  ============================================
echo    CAI DAT HOAN TAT!
echo    Tu gio chi can nhan doi icon "Rightly"
echo    tren Desktop la dung duoc ngay.
echo  ============================================
echo.
set /p launch="Mo thu dung luon bay gio? (Y/N): "
if /i "%launch%"=="Y" call "%~dp0Rightly.bat"
