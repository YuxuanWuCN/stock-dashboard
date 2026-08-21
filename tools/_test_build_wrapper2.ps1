# _test_build_wrapper2.ps1 —— 完全复刻 morning 的 build_ranking 段
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:STOCK_PROXY = "direct"
$env:LLM_DAILY_CALL_LIMIT = "800"
$py = Join-Path $repo ".venv\Scripts\python.exe"
$logFile = Join-Path $repo ".quality-state\daily_morning.log"

Write-Output ("复刻测试开始: " + (Get-Date -Format "HH:mm:ss"))
$sw = [System.Diagnostics.Stopwatch]::StartNew()
& $py -m src.build_ranking *>> $logFile
$sw.Stop()
Write-Output ("build_ranking 退出码: " + $LASTEXITCODE + " 耗时: " + [Math]::Round($sw.Elapsed.TotalSeconds, 1) + "s  结束: " + (Get-Date -Format "HH:mm:ss"))
