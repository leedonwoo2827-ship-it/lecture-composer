@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv-app\Scripts\python.exe" (
  echo [ERROR] Not set up yet. Run setup.bat first.
  echo.
  pause
  exit /b 1
)

REM --- Keep the console from freezing the server ------------------------
REM Windows QuickEdit: one click inside the window enters selection mode,
REM which blocks console output and HALTS the whole process. It looks like
REM the app got slow, but the server is frozen (title turns to 'Select ...').
REM Console settings are read when the window is created, so we write the
REM per-title key first and then hand off to a fresh window.
reg add "HKCU\Console\Developer Showcase Agent" /v QuickEdit /t REG_DWORD /d 0 /f >nul 2>&1

if "%SA_CONSOLE%"=="1" goto serve
set "SA_CONSOLE=1"
REM ★ /k, not /c — /c closes the window the instant the script ends, so the
REM   "press any key" after a crash immediately kills the window with it —
REM   one keypress and the error log is gone, unreadable (2026-08-13 report).
REM   /k leaves a plain prompt in the same window after the script ends, so
REM   the crash log stays on screen (scrollable) until closed by hand.
start "Developer Showcase Agent" cmd /k ""%~f0""
exit /b

:serve
set "PORT=5178"
if not "%SHOWCASE_PORT%"=="" set "PORT=%SHOWCASE_PORT%"
set "SHOWCASE_OPEN_BROWSER=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo Developer Showcase Agent  ^> http://localhost:%PORT%
echo Press Ctrl+C to stop.
echo.

REM --no-access-log is a safety belt, not a preference: the less we write to
REM the console, the less a stray click can stall. Progress is on screen.
".venv-app\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port %PORT% --no-access-log

REM Keep the window open so a startup crash stays readable
echo.
echo Server stopped (exit code %ERRORLEVEL%).
pause
