@echo off
rem simLIBS Studio launcher (ASCII only; starts the native desktop app)
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PY=%SIMLIBS_UI_PYTHON%"
if not defined PY set "PY=E:\Anaconda\envs\simLIBS\python.exe"
if not exist "%PY%" set "PY=D:\Anaconda\envs\simLIBS\python.exe"
if not exist "%PY%" (
  echo [simLIBS] Python interpreter not found: %PY%
  echo Set SIMLIBS_UI_PYTHON to a Python 3.10+ python.exe and retry.
  pause
  exit /b 1
)
set "PYTHONUTF8=1"
set "CRASHLOG=%TEMP%\simlibs-cli-stderr.log"
echo Starting simLIBS Studio ...
"%PY%" -B run_qt.py %* 2> "%CRASHLOG%"
set "RC=%errorlevel%"
if not "%RC%"=="0" goto failed
del "%CRASHLOG%" 2>nul
exit /b 0
:failed
echo.
echo [simLIBS] Exited with error code %RC%. Details (app exceptions also in CLI\last-crash.log):
echo ----------------------------------------------------
type "%CRASHLOG%"
echo ----------------------------------------------------
echo Please paste the text above when reporting the issue.
pause
exit /b 1
