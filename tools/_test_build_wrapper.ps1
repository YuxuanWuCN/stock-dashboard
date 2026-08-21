# _test_build_wrapper.ps1 —— 模拟 daily_morning.ps1 的嵌套调用方式
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:STOCK_PROXY = "direct"
$env:LLM_DAILY_CALL_LIMIT = "800"
$py = Join-Path $repo ".venv\Scripts\python.exe"
$logFile = Join-Path $repo ".quality-state\_nested_test.log"

Write-Output ("嵌套测试开始: " + (Get-Date -Format "HH:mm:ss"))
& $py -m src.build_ranking *>> $logFile
Write-Output ("build_ranking 退出码: " + $LASTEXITCODE + "  结束: " + (Get-Date -Format "HH:mm:ss"))
Write-Output ("日志大小: " + (Get-Item $logFile).Length)
Remove-Item $logFile -Force -ErrorAction SilentlyContinue
