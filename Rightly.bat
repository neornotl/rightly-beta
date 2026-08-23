@echo off
chcp 65001 >nul
title Rightly - Tro Ly Phap Ly Tieng Lang
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Ban chua cai dat! Hay chay file "CaiDat-Rightly.bat" truoc nhe.
    pause
    exit /b 1
)

echo Dang khoi dong Rightly... (trinh duyet se tu mo sau ~20 giay)
start "" http://localhost:8010

call ".venv\Scripts\activate.bat"
python -m uvicorn webhook_server:app --host 127.0.0.1 --port 8010

echo.
echo Server da dung. Cua so nay co the dong an toan.
pause
