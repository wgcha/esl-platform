@echo off
rem ESL demo stop (double-click). Arguments are passed to stop-demo.ps1.
rem Reset PSModulePath so Windows PowerShell 5.1 loads its own modules even when called from pwsh 7.
set PSModulePath=
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-demo.ps1" %*
set ESL_RC=%ERRORLEVEL%
if "%ESL_NO_PAUSE%"=="" pause
exit /b %ESL_RC%
