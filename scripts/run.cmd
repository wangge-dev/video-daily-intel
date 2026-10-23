@echo off
chcp 65001 >nul 2>nul
setlocal
rem Unified entry point. Probes several runtimes, uses the first one found.
rem Force a specific interpreter: set VDI_PYTHON=D:////some////python.exe

set "PYEXE="

if defined VDI_PYTHON if exist "%VDI_PYTHON%" set "PYEXE=%VDI_PYTHON%"

if not defined PYEXE if exist "%USERPROFILE%\.workbuddy\vdi-runtime\Scripts\python.exe" set "PYEXE=%USERPROFILE%\.workbuddy\vdi-runtime\Scripts\python.exe"
if not defined PYEXE if exist "%~dp0..\.venv\Scripts\python.exe" set "PYEXE=%~dp0..\.venv\Scripts\python.exe"
if not defined PYEXE if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\douyin312\Scripts\python.exe" set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\envs\douyin312\Scripts\python.exe"
if not defined PYEXE if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\douyin\Scripts\python.exe" set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\envs\douyin\Scripts\python.exe"

if not defined PYEXE (
  echo [ERROR] Runtime not found. Run this first:
  echo     python "%~dp0install.py"
  exit /b 1
)

set "PYTHONIOENCODING=utf-8"
for %%I in ("%PYEXE%") do set "PYDIR=%%~dpI"
set "PATH=%PYDIR%;%PATH%"
"%PYEXE%" "%~dp0runner.py" %*
