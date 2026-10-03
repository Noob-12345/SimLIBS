param([Parameter(ValueFromRemainingArguments=$true)][string[]]$UiArguments)
$ErrorActionPreference = 'Stop'
$simlibsPythonPath = $env:SIMLIBS_UI_PYTHON
if (-not $simlibsPythonPath) { $simlibsPythonPath = 'D:\Anaconda3\envs\simLIBS\python.exe' }
if (-not (Test-Path -LiteralPath $simlibsPythonPath -PathType Leaf)) {
    throw "Python 解释器不存在：$simlibsPythonPath。请设置 SIMLIBS_UI_PYTHON 为已有 Python 3.10+ 环境。"
}
& $simlibsPythonPath -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) { throw '需要 Python 3.10+；默认 Anaconda Python 3.7 不适用。' }
$env:PYTHONUTF8 = '1'
& $simlibsPythonPath -B (Join-Path $PSScriptRoot 'run_ui.py') @UiArguments
exit $LASTEXITCODE
