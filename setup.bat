@echo off
setlocal
cd /d "%~dp0"
rem ==========================================================================
rem  Lecture Composer - first-time setup (safe to run again)
rem
rem  NOTE: keep this file ASCII only and CRLF only (same rule as backplate).
rem  cmd.exe reads a .bat with the console codepage (CP949 on Korean Windows):
rem  UTF-8 Korean breaks parsing, and LF-only line ends break labels/goto.
rem  Korean messages belong in the Python code, not here.
rem
rem  Everything is installed INSIDE this folder. No other folder or repo is
rem  used: the render engine is vendored in engine\backplate.
rem  Needs on PATH: python 3.11-3.13, node 22+, git (+git-lfs for voice
rem  weights), ffmpeg. Plus Google Chrome, claude CLI, codex CLI (logged in).
rem ==========================================================================

echo [1/3] Pipeline venv (.venv)
where python >nul 2>&1
if errorlevel 1 (
  echo   [!] python not found on PATH. Install Python 3.11-3.13.
  goto :fail
)
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 goto :fail
)
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -r requirements.txt
if errorlevel 1 goto :fail
.venv\Scripts\python -m playwright install chromium
if errorlevel 1 goto :fail

echo [2/3] Render engine (engine\backplate: 2 venvs, npm, fonts, voice weights)
if not exist engine\backplate\setup.bat (
  echo   [!] engine\backplate is missing. Re-clone this repo.
  goto :fail
)
if exist engine\backplate\.venv-app\Scripts\python.exe (
  if exist engine\backplate\node_modules (
    echo   already installed - to redo, run engine\backplate\setup.bat
    goto :check
  )
)
call "%~dp0engine\backplate\setup.bat"
cd /d "%~dp0"

:check
echo [3/3] Check
where ffmpeg >nul 2>&1
if errorlevel 1 echo   [!] ffmpeg not found on PATH
where node >nul 2>&1
if errorlevel 1 echo   [!] node not found on PATH - Node 22+
where claude >nul 2>&1
if errorlevel 1 (
  if exist "%USERPROFILE%\.vscode\extensions\anthropic.claude-code-*" (
    echo   claude: using the VSCode extension binary
  ) else (
    echo   [!] claude not found - install Claude Code, then run claude once to log in
  )
)
where codex >nul 2>&1
if errorlevel 1 echo   [!] codex CLI not found - needed for background images - codex login
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
  echo   Chrome OK
) else (
  echo   [!] Chrome not at default path - set youtube.chrome in jobs\JOB\job.local.json
)
if exist engine\backplate\.venv-app\Scripts\python.exe (
  engine\backplate\.venv-app\Scripts\python engine\backplate\tools\doctor.py
)

echo.
echo Done. Next: double-click run.bat - web app at http://127.0.0.1:5190
echo       CLI : run.bat all --only L01 --sections 1
pause
exit /b 0

:fail
echo.
echo [FAILED] See the message above.
pause
exit /b 1
