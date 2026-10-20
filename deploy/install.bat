@echo off
rem ESL server install from the offline bundle (Windows PowerShell 5.1). Arguments are passed to install.ps1.
rem Not the user-PC TCL updater: the repository root update.bat is for HyperView TCL on user PCs.
rem Reset PSModulePath so Windows PowerShell 5.1 loads its own modules even when called from pwsh 7.
set PSModulePath=
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
