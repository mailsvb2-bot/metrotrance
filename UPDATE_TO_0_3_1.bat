@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MetroTrance 0.3.1 Update
echo MetroTrance 0.3.1 Strict Voice Lab
echo.
if not exist "metrotrance\services\voice_quality.py" (
  echo ERROR: Extract the 0.3.1 files into the MetroTrance root folder.
  pause
  exit /b 1
)
del /q "data\voice\quality_approval.json" >nul 2>nul
del /q "data\voice\approved_candidate.wav" >nul 2>nul
echo Previous voice approval was reset because the verification fingerprint changed.
call RESTART_METROTRANCE.bat
