@echo off
setlocal
chcp 65001 >nul
set "SIMLIBS_PYTHON=%SIMLIBS_UI_PYTHON%"
if not defined SIMLIBS_PYTHON set "SIMLIBS_PYTHON=D:\Anaconda3\envs\simLIBS\python.exe"
if not exist "%SIMLIBS_PYTHON%" (
  echo Python 解释器不存在：%SIMLIBS_PYTHON%
  echo 请设置 SIMLIBS_UI_PYTHON 为已有 Python 3.10+ 环境的 python.exe 路径。
  pause
  exit /b 1
)
"%SIMLIBS_PYTHON%" -B -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo 需要 Python 3.10+；请使用 D:\Anaconda3\envs\simLIBS\python.exe。
  pause
  exit /b 1
)
set "PYTHONUTF8=1"
"%SIMLIBS_PYTHON%" -B "%~dp0run_ui.py" %*
if errorlevel 1 (
  echo 应用退出异常，请检查上方错误或运行 --diagnose。
  pause
  exit /b 1
)
endlocal
