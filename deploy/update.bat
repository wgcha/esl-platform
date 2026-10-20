@echo off
rem ESL server update from a new offline bundle (Windows PowerShell 5.1). Arguments are passed to update.ps1 (-Force etc.).
rem Not the user-PC TCL updater: the repository root update.bat is for HyperView TCL on user PCs.
rem Reset PSModulePath so Windows PowerShell 5.1 loads its own modules even when called from pwsh 7.
set PSModulePath=
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1" %*
