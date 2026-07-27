@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MetroTrance 0.3.0 Repair
echo MetroTrance 0.3.0 repair
echo.
call "%~dp0REPAIR_RUSSIAN_STRESS_MODEL.bat" /quiet
if errorlevel 1 (
  echo ERROR: Russian stress repair failed.
  pause
  exit /b 1
)
echo.
echo Russian stress model is verified. Starting MetroTrance...
call "%~dp0START_METROTRANCE.bat"
exit /b %ERRORLEVEL%
