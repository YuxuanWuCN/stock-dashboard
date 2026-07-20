@echo off
cd /d "%~dp0"
title Stock Dashboard 2.0
python start_local.py
if errorlevel 1 (
    echo.
    echo Startup failed. Read the message above, then press any key to close.
    pause >nul
)
