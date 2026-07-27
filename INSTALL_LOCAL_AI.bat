@echo off
setlocal
cd /d "%~dp0"
set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" windows_installer.py --llm-only
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" pause
exit /b %CODE%
