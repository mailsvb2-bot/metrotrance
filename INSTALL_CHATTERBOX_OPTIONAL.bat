@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MetroTrance Chatterbox Setup
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
%PYSEL% "%~dp0windows_installer.py" --chatterbox-only --no-launch
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo Chatterbox installation completed.
if not "%RC%"=="0" echo Chatterbox installation failed.
pause
exit /b %RC%
