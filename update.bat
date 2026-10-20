@echo off
rem esl-platform one-click update: git pull (fast-forward only), deploy HyperView TCL, create ESL_probe.bat / ESL_extract.bat / ESL_upload.bat
rem Double-click this file. Details: README.md "Windows install / update".
setlocal DisableDelayedExpansion
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\update.ps1" %*
if errorlevel 1 (
  echo.
  echo [FAILED] Update did not complete. Read the messages above. Log: %%LOCALAPPDATA%%\esl\logs
  pause
  exit /b 1
)
echo.
echo [OK] Update finished. Drag h3d (+ rad) files onto ESL_probe.bat / ESL_extract.bat in the folder shown above.
pause
exit /b 0
