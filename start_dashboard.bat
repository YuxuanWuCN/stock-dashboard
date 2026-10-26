@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Rainbow-FinGPT Research Terminal
set "PY_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
)
"%PY_EXE%" start_dashboard.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Dashboard launcher exited with an error.
    pause
)
