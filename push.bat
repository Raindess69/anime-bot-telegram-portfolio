@echo off
cd /d "%~dp0"

echo ============================================================
echo   Pushing Anime Bot to GitHub
echo ============================================================
echo.

git push -u origin main

if errorlevel 1 goto on_error

echo.
echo ============================================================
echo   [SUCCESS] Repository successfully pushed to GitHub!
echo ============================================================
goto end

:on_error
echo.
echo ============================================================
echo   [ERROR] Push failed.
echo   1. Check that repository exists on GitHub:
echo      https://github.com/Raindess69/anime-bot-telegram-portfolio
echo   2. Authorize in GitHub when prompted in the browser.
echo ============================================================

:end
echo.
pause
