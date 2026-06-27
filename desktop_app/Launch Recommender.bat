@echo off
REM Double-click launcher for the PyQt6 game recommender.

setlocal enabledelayedexpansion
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not on PATH. Install from https://python.org and retry.
    pause
    exit /b 1
)

python -c "import PyQt6, supabase, requests" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies (one-time)...
    python -m pip install --quiet PyQt6 supabase requests
)

REM Load .env if present (simple parser: KEY=VALUE lines, skips comments)
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "line=%%A"
        if not "!line:~0,1!"=="#" if not "!line!"=="" (
            set "%%A=%%B"
        )
    )
)

if "%SUPABASE_URL%"=="" (
    echo SUPABASE_URL is not set. Copy .env.example to .env and fill it in.
    pause
    exit /b 1
)
if "%SUPABASE_ANON_KEY%"=="" (
    echo SUPABASE_ANON_KEY is not set. Copy .env.example to .env and fill it in.
    pause
    exit /b 1
)

start "" pythonw app.py
