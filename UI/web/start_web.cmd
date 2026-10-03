@echo off
rem simLIBS Web UI 启动器。仅使用现有 Python 环境，不修改任何现有程序文件。
setlocal
set "PY=D:\Anaconda3\envs\simLIBS\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -B "%~dp0server.py" %*
endlocal
