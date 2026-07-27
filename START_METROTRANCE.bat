@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MetroTrance
if not defined PUBLIC set "PUBLIC=C:\Users\Public"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
set "RUNPY="
set "SHORTPY=%LOCALAPPDATA%\MetroTrance\venv\Scripts\python.exe"
set "LOCALPY=%~dp0.venv\Scripts\python.exe"
if exist "%SHORTPY%" set "RUNPY=%SHORTPY%"
if not defined RUNPY if exist "%LOCALPY%" set "RUNPY=%LOCALPY%"
if not defined RUNPY (
  echo ERROR: MetroTrance Python runtime was not found.
  echo Run INSTALL_WINDOWS.bat once.
  pause
  exit /b 1
)
set "ASCII_MODEL=%PUBLIC%\MetroTrance\models\silero_stress\accentor.pt"
if not exist "%ASCII_MODEL%" (
  echo Preparing Russian stress model in an ASCII-only path...
  call "%~dp0REPAIR_RUSSIAN_STRESS_MODEL.bat" /quiet
  if errorlevel 1 (
    echo ERROR: Russian stress model could not be prepared.
    pause
    exit /b 1
  )
)
if not exist "%~dp0data\logs" mkdir "%~dp0data\logs" >nul 2>nul
"%RUNPY%" "%~dp0metrotrance_launcher.py"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
