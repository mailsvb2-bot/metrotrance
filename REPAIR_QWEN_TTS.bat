@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MetroTrance Qwen3-TTS Repair
set "PYSEL="
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYSEL=py -3.12"
if not defined PYSEL (
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PYSEL=py -3.11"
)
if not defined PYSEL (
  echo ERROR: Python 3.11 or 3.12 x64 was not found.
  pause
  exit /b 1
)
%PYSEL% "%~dp0windows_installer.py" --tts-only --no-launch
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo Qwen3-TTS repair completed. Run START_METROTRANCE.bat.
) else (
  echo Qwen3-TTS repair failed. See data\logs\install.log.
)
pause
exit /b %RC%
