@echo off
REM One-command launcher for ExcelLence AI (Windows)
cd /d "%~dp0backend"

REM Activate venv if present
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "..\venv\Scripts\activate.bat" (
    call ..\venv\Scripts\activate.bat
)

REM Copy .env.example on first run
if not exist ".env" (
    copy .env.example .env >nul
    echo.
    echo  WARNING: Created backend\.env from .env.example.
    echo  Please open it and set GROQ_API_KEY before continuing.
    echo  Get a free key at: https://console.groq.com/keys
    echo.
    pause
    exit /b 1
)

echo Starting ExcelLence AI at http://127.0.0.1:8000
uvicorn main:app --reload --host 127.0.0.1 --port 8000
