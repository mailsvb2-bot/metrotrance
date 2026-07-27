@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MetroTrance Setup 0.1.3
set "PYSEL="
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYSEL=py -3.12"
if not defined PYSEL (
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PYSEL=py -3.11"
)
if not defined PYSEL (
  echo ERROR: Python 3.11 or 3.12 x64 was not found.
  echo Install Python with the Python Launcher option enabled.
  pause
  exit /b 1
)
%PYSEL% "%~dp0windows_installer.py"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
