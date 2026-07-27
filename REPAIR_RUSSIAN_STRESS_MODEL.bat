@echo off
setlocal EnableExtensions
cd /d "%~dp0"
for %%I in ("%CD%") do set "PROJECT_ROOT=%%~fI"
title MetroTrance Russian Stress Repair
if not defined PUBLIC set "PUBLIC=C:\Users\Public"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%PROJECT_ROOT%;%PYTHONPATH%"
set "RUNPY="
set "SHORTPY=%LOCALAPPDATA%\MetroTrance\venv\Scripts\python.exe"
set "LOCALPY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
if exist "%SHORTPY%" set "RUNPY=%SHORTPY%"
if not defined RUNPY if exist "%LOCALPY%" set "RUNPY=%LOCALPY%"
if not defined RUNPY (
  echo ERROR: MetroTrance Python runtime was not found.
  echo Run INSTALL_WINDOWS.bat once.
  if /I not "%~1"=="/quiet" pause
  exit /b 1
)
set "SOURCE_MODEL=%PROJECT_ROOT%\metrotrance\resources\silero_stress\accentor.pt"
set "ASCII_MODEL=%PUBLIC%\MetroTrance\models\silero_stress\accentor.pt"
echo Runtime:      %RUNPY%
echo Project:      %PROJECT_ROOT%
echo Source model: %SOURCE_MODEL%
echo ASCII model:  %ASCII_MODEL%
"%RUNPY%" "%PROJECT_ROOT%\repair_russian_stress.py" --project-root "%PROJECT_ROOT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo ERROR: Russian stress model repair failed with code %RC%.
  if /I not "%~1"=="/quiet" pause
  exit /b %RC%
)
if /I not "%~1"=="/quiet" pause
exit /b 0
