@echo off
setlocal
cd /d "%~dp0"
rem NOTE: ASCII only, CRLF only. Korean text goes in Python, not in .bat files.
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if "%~1"=="" goto :web

rem With arguments = CLI (for agents and scripts). e.g. run.bat all --only L01 --sections 1
.venv\Scripts\python -m longform %*
exit /b %errorlevel%

:web
rem No arguments (double-click) = web app http://127.0.0.1:5190
.venv\Scripts\python -m longform.web.server
if errorlevel 1 pause
exit /b %errorlevel%
