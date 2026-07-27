@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MetroTrance Diagnostic Console
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
set "METROTRANCE_OPEN_BROWSER=1"
"%RUNPY%" -m metrotrance
set "RC=%ERRORLEVEL%"
echo.
echo Server stopped with code %RC%.
pause
exit /b %RC%
