@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title MetroTrance Restart
set "PIDFILE=%~dp0data\logs\server.pid"
set "MTPID="
if exist "%PIDFILE%" set /p MTPID=<"%PIDFILE%"
if not defined MTPID (
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":8765 .*LISTENING"') do set "MTPID=%%P"
)
if defined MTPID taskkill /PID !MTPID! /T /F >nul 2>nul
if exist "%PIDFILE%" del /q "%PIDFILE%" >nul 2>nul
timeout /t 2 /nobreak >nul
call "%~dp0START_METROTRANCE.bat"
