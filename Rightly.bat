@echo off
chcp 65001 >nul
setlocal
title Rightly - Tro ly phap ly offline
cd /d "%~dp0"

rem After setup, launch the native app directly.  The one-file launcher is
rem copied beside this script in the user's private Rightly folder.
if exist "Rightly.exe" (
  start "Rightly" "%~dp0Rightly.exe"
  exit /b 0
)
rem Development checkout compatibility: use the build output if present.
if exist "dist\Rightly.exe" (
  start "Rightly" "%~dp0dist\Rightly.exe"
  exit /b 0
)

echo.
echo  ==========================================
echo   Rightly - khoi dong che do offline
echo  ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [LOI] Rightly chua duoc cai dat day du.
  echo       Hay chay CaiDat-Rightly.bat mot lan khi co internet.
  pause
  exit /b 1
)
if not exist ".env" (
  echo [LOI] Thieu cau hinh offline .env.
  echo       Hay chay CaiDat-Rightly.bat mot lan khi co internet.
  pause
  exit /b 1
)

if not exist "logs" mkdir "logs"
echo Dang khoi dong server, vui long doi den khi san sang...
start "Rightly server" /b cmd /c ""%~dp0.venv\Scripts\python.exe" "%~dp0webhook_server.py" > "%~dp0logs\rightly-server.log" 2>&1"
start "Rightly health" /min powershell -NoProfile -Command ^
 "$ok=$false; for($i=0;$i -lt 90;$i++){try{$r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/health -TimeoutSec 2;if($r.StatusCode -eq 200){$ok=$true;Start-Process 'http://localhost:8010';break}}catch{};Start-Sleep 1}; if(-not $ok){Write-Host 'Rightly chua san sang. Xem logs\rightly-server.log';Read-Host 'Nhan Enter de dong'}"

echo Trinh duyet se mo sau khi server qua health check.
echo Dong cua so nay de dung server.
pause
endlocal
