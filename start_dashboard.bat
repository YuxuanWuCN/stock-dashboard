@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Rainbow-FinGPT Research Terminal
python start_dashboard.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Dashboard launcher exited with an error.
    pause
)
