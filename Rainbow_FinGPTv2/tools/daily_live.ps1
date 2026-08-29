# tools/daily_live.ps1 —— 组员本地一键运行日常真实大模型投研流水线
param(
    [string]$Backend = ""
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "🌟 Rainbow-FinGPT 每日全链路大模型投研与长跑中枢" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

# 检查当前目录
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

# 环境变量传递
if ($Backend -ne "") {
    $env:LLM_BACKEND = $Backend
    Write-Host "[INFO] 指定大模型推理后端: $Backend" -ForegroundColor Yellow
}

# 1. 执行 LLM 连接性诊断
Write-Host "
[1/3] 正在诊断本地 API Key / Ollama 连通性..." -ForegroundColor Cyan
python -c "from src.llm.llm_client import diagnose_llm_connection; diagnose_llm_connection(True)"

# 2. 执行绿电板块实时投研
Write-Host "
[2/3] 启动绿电公用事业板块实时大模型事实抽取与策略调仓..." -ForegroundColor Cyan
python -m src.analysis.green_backtest_runner --live-llm

# 3. 运行全量日常流水线
Write-Host "
[3/3] 正在刷新模拟盘与前端交互看板..." -ForegroundColor Cyan
python tools/daily_routine.py --skip-push

Write-Host "
==========================================================" -ForegroundColor Green
Write-Host "✅ 今日全流程实时投研与策略长跑执行完成！" -ForegroundColor Green
Write-Host "💡 您可以运行: python -m src.server 打开本地 Web 看板查看最新研报" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Green
