@echo off
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"

rem One-click installer for video-daily-intel.
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD (
  where python >nul 2>nul && set "PYCMD=python"
)
if not defined PYCMD (
  echo [ERROR] Python not found.
  echo Download Python 3.10+ from https://www.python.org/downloads/
  echo Remember to tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)

echo Installing video-daily-intel runtime, please wait...
echo.
%PYCMD% "scripts\install.py" %*
if errorlevel 1 (
  echo.
  echo [ERROR] Install failed. Please check the messages above.
  pause
  exit /b 1
)

echo.
echo All done. Now open WorkBuddy and say: start video intel
pause
