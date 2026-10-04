@echo off
chcp 65001 >nul
rem simLIBS Web UI 启动器。仅使用现有 Python 环境，不修改任何现有程序文件。
setlocal
set "SIMLIBS_WEB_PYTHON=%SIMLIBS_UI_PYTHON%"
if not defined SIMLIBS_WEB_PYTHON (
  if exist "E:\Anaconda\envs\simLIBS\python.exe" (
    set "SIMLIBS_WEB_PYTHON=E:\Anaconda\envs\simLIBS\python.exe"
  ) else (
    set "SIMLIBS_WEB_PYTHON=D:\Anaconda3\envs\simLIBS\python.exe"
  )
)
if not exist "%SIMLIBS_WEB_PYTHON%" (
  echo Python 解释器不存在，请设置 SIMLIBS_UI_PYTHON 为已有 Python 3.10+ 环境。
  exit /b 1
)
set "PYTHONUTF8=1"
"%SIMLIBS_WEB_PYTHON%" -B "%~dp0server.py" %*
endlocal
