@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
    echo [setup] Creating virtual environment...
    python -m venv .venv || goto :error
)

call ".venv\Scripts\activate.bat" || goto :error

if not exist ".venv\.installed" (
    echo [setup] Installing dependencies...
    python -m pip install --upgrade pip >nul
    pip install -r requirements.txt || goto :error
    type nul > ".venv\.installed"
)

if not exist ".env" (
    echo.
    echo [!] File .env is missing.
    echo     Copy .env.example to .env and paste your BOT_TOKEN from @BotFather.
    echo.
    pause
    exit /b 1
)

echo [run] Starting bot...
python bot.py
goto :eof

:error
echo.
echo [x] Setup failed. See errors above.
pause
exit /b 1
