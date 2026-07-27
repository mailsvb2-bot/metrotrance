@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0REPAIR_RUSSIAN_STRESS_MODEL.bat" %*
exit /b %ERRORLEVEL%
