@echo off
rem ESL demo start (double-click, no Altair needed). Arguments are passed to start-demo.ps1.
rem Reset PSModulePath so Windows PowerShell 5.1 loads its own modules even when called from pwsh 7.
set PSModulePath=
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-demo.ps1" %*
set ESL_RC=%ERRORLEVEL%
if "%ESL_NO_PAUSE%"=="" pause
exit /b %ESL_RC%
