@echo off
chcp 65001 >nul
title Tai mo hinh AI offline (Ollama)
echo Dang tai qwen2.5:3b (~1.9GB) - can internet on dinh...
ollama pull qwen2.5:3b-instruct-q4_K_M
if errorlevel 1 (
  echo.
  echo Tai loi (mang chuan den may chu Ollama). Thu lai lan nua?
  pause
  ollama pull qwen2.5:3b-instruct-q4_K_M
)
ollama list
pause
