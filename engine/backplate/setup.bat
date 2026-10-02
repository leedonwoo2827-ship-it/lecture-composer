@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
rem Console to UTF-8 so the Python tools can print Korean without dying.
rem This file itself stays ASCII - see the note below.
chcp 65001 >nul
set PYTHONUTF8=1

rem ===========================================================================
rem  backplate-showcase - first-time setup
rem
rem  NOTE (ASCII only, CRLF only). Do NOT put Korean text in this file.
rem  cmd.exe parses a .bat with the *console* codepage. On a Korean console
rem  (CP949) UTF-8 multibyte gets mis-read as command separators and the
rem  script falls apart ("'--upgrade' is not recognized"). Korean messages
rem  belong in tools\doctor.py, which is Python and handles UTF-8 properly.
rem  Also: LF-only .bat breaks label/goto. Keep CRLF.
rem
rem  Everything happens inside THIS folder. No sibling project paths, so a
rem  teammate or a spare PC works the same. Safe to run repeatedly.
rem ===========================================================================

echo == backplate-showcase : first-time setup ==
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python 3.11-3.13 not found on PATH.
  goto :fail
)
where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node 22+ not found on PATH. HyperFrames needs it.
  goto :fail
)

echo [1/6] console env ^(.venv-app^)
if not exist ".venv-app\Scripts\python.exe" python -m venv .venv-app
if errorlevel 1 (echo [ERROR] venv creation failed. & goto :fail)
".venv-app\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv-app\Scripts\python.exe" -m pip install --quiet -e .
if errorlevel 1 (echo [ERROR] dependency install failed. & goto :fail)

echo [2/6] engine env ^(.venv^) - onnxruntime is kept apart from the console
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 echo [WARN] engine venv failed - narration audio will be skipped.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements-engine.txt
  if errorlevel 1 echo [WARN] engine deps failed - narration audio will be skipped.
)

echo [3/6] node packages ^(HyperFrames + Playwright^)
call npm install --silent
if errorlevel 1 (echo [ERROR] npm install failed. & goto :fail)

echo [4/6] fonts ^(Pretendard^)
".venv-app\Scripts\python.exe" tools\get_fonts.py

echo [5/6] voice model ^(Supertonic 3, ~396MB^)
if exist "assets\onnx\vocoder.onnx" (
  echo        already present.
  goto :tts_wire
)
rem If this PC already has a copy, set SUPERTONIC_ASSETS_SRC to it and we copy.
rem We do NOT hardcode a sibling path - that path only exists on one machine.
if defined SUPERTONIC_ASSETS_SRC (
  if exist "!SUPERTONIC_ASSETS_SRC!\onnx\vocoder.onnx" (
    echo        copying from !SUPERTONIC_ASSETS_SRC!
    robocopy "!SUPERTONIC_ASSETS_SRC!" "assets" /E /NFL /NDL /NJH /NJS /XD ".git" >nul
  )
)
if exist "assets\onnx\vocoder.onnx" goto :tts_wire
where git-lfs >nul 2>&1
if errorlevel 1 (
  echo        [WARN] git-lfs missing - model not downloaded.
  echo               Install https://git-lfs.com then re-run setup.bat.
  echo               ^(Only narration audio is affected; deck/subtitles still work.^)
  goto :tts_wire
)
echo        downloading - a few minutes depending on your link.
git lfs install --skip-repo >nul 2>&1
git clone --depth 1 https://huggingface.co/Supertone/supertonic-3 assets
if errorlevel 1 echo        [WARN] download failed - narration audio will be skipped.

:tts_wire
".venv-app\Scripts\python.exe" tools\wire_tts.py

echo [6/6] diagnostics
".venv-app\Scripts\python.exe" tools\doctor.py
if errorlevel 1 (
  echo.
  echo Fix the items marked with X above, then run setup.bat again.
  pause
  exit /b 1
)

echo.
echo Setup complete. Start with run.bat
echo.
echo   Two logins are PER PERSON - setup cannot do them for you:
echo     claude        run once to sign in  ^(script + image directions^)
echo     codex login   run once to sign in  ^(image generation^)
echo.
pause
exit /b 0

:fail
echo.
echo Setup did not finish. The message above says why.
pause
exit /b 1
