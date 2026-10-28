@echo off
rem ESL server stop (Windows PowerShell 5.1, no admin needed). Optional: -Only backend|worker, -Force (no Y/N prompt).
rem Reset PSModulePath so Windows PowerShell 5.1 loads its own modules even when called from pwsh 7.
set PSModulePath=
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0esl-service.ps1" -Action stop %*
pause
