@echo off
rem ============================================================
rem  simLIBS Studio (WPF) launcher
rem  Double-click to start. Builds on first run using the
rem  bundled .NET 10 SDK in the .dotnet folder.
rem  NOTE: keep this file ASCII-only (cmd.exe parses batch
rem  files in the ANSI codepage; UTF-8 comments break parsing)
rem ============================================================
setlocal
cd /d "%~dp0"

rem bundled user-level .NET SDK, no system-wide install needed
if exist "%~dp0.dotnet\dotnet.exe" set "DOTNET_ROOT=%~dp0.dotnet"

set "EXE=src\SimlibsStudio\bin\Debug\net10.0-windows\SimlibsStudio.exe"

if exist "%EXE%" goto :run

echo First run: building simLIBS Studio ...
if exist "%~dp0.dotnet\dotnet.exe" (
    "%~dp0.dotnet\dotnet.exe" build src\SimlibsStudio\SimlibsStudio.csproj -v q -nologo
) else (
    dotnet build src\SimlibsStudio\SimlibsStudio.csproj -v q -nologo
)
if errorlevel 1 goto :fail
if not exist "%EXE%" goto :fail

:run
echo Starting simLIBS Studio ...
"%EXE%" %*
if errorlevel 1 (
    echo.
    echo [ERROR] simLIBS Studio exited with code %errorlevel%.
    pause
)
exit /b 0

:fail
echo.
echo [ERROR] Build failed. See messages above.
echo Common causes: missing Python env (E:\Anaconda\envs\simLIBS)
echo or antivirus blocking the build.
pause
exit /b 1
