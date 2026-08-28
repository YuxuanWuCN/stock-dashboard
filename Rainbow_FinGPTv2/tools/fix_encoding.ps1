# fix_encoding.ps1 —— 修复已有 JSON 文件的中文乱码问题
#
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File tools\fix_encoding.ps1

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# 强制 UTF-8 编码
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

$py = Join-Path $repo ".venv\Scripts\python.exe"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "修复 JSON 文件中文乱码" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "⚠️  警告：此操作会重新生成所有数据文件" -ForegroundColor Yellow
Write-Host "   建议先备份 docs/data/ 目录" -ForegroundColor Yellow
Write-Host ""

$confirm = Read-Host "是否继续？(y/n)"
if ($confirm -ne 'y') {
    Write-Host "已取消" -ForegroundColor Gray
    exit 0
}

Write-Host ""
Write-Host "步骤 1/4: 重新抓取数据..." -ForegroundColor Green
& $py -m src.fetch_data
Write-Host ""

Write-Host "步骤 2/4: 重新生成排行榜..." -ForegroundColor Green
& $py -m src.build_ranking
Write-Host ""

Write-Host "步骤 3/4: 重新生成策略数据..." -ForegroundColor Green
& $py -m src.strategies.main --scope watchlist
Write-Host ""

Write-Host "步骤 4/4: 重新生成模拟盘数据..." -ForegroundColor Green
& $py tools\paper_portfolio.py report
& $py tools\paper_portfolio.py benchmark
& $py tools\paper_portfolio.py manifest
Write-Host ""

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "✅ 修复完成！" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "请检查以下文件的中文是否正常：" -ForegroundColor Yellow
Write-Host "  - docs/data/summary.json"
Write-Host "  - docs/data/paper/performance.json"
Write-Host "  - docs/data/paper/performance_aggressive.json"
Write-Host ""
