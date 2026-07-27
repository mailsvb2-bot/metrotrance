@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MetroTrance Check
set "RUNPY="
set "SHORTPY=%LOCALAPPDATA%\MetroTrance\venv\Scripts\python.exe"
if exist "%SHORTPY%" (
  "%SHORTPY%" -c "import metrotrance" >nul 2>nul
  if not errorlevel 1 set "RUNPY=%SHORTPY%"
)
if not defined RUNPY if exist "%~dp0.venv\Scripts\python.exe" set "RUNPY=%~dp0.venv\Scripts\python.exe"
if not defined RUNPY (
  echo ERROR: MetroTrance runtime was not found.
  echo Run INSTALL_WINDOWS.bat first.
  pause
  exit /b 1
)
"%RUNPY%" "%~dp0metrotrance_launcher.py" --check-only
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo Check completed successfully.
if not "%RC%"=="0" echo Check failed with code %RC%.
pause
exit /b %RC%
