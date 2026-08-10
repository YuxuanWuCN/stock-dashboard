# daily_morning.ps1 —— 早上 8:00 美股补数据任务
#
# 背景：晚上 18:00 运行时美股尚未开盘，美股行情停留在上一个美股交易日（滞后一天）。
# 本任务在美股收盘后（北京时间次日早上）重新抓取全市场数据，重新生成排行榜/AI研报
# （已有研报自动跳过，不重复消耗 API），并重写模拟盘绩效（按 trade_date 去重覆盖），
# 使美股数据与 A股/港股对齐到同一交易日。
#
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File tools\daily_morning.ps1
#
# 流程：抓取行情 → 排行榜+基本面+LLM研报 → 模拟盘记录 → 提交推送 GitHub

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:STOCK_PROXY = "direct"  # 直连模式：避免 Clash 代理导致连接失败
$env:LLM_DAILY_CALL_LIMIT = "800"
$py = Join-Path $repo ".venv\Scripts\python.exe"
$logFile = Join-Path $repo ".quality-state\daily_morning.log"

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Output $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

Write-Log "=== 早上美股补数据开始 ==="

# 1) 抓取行情（美股补上昨日收盘；A股/港股无新数据时保持原样）
& $py -m src.fetch_data *>> $logFile
Write-Log ("fetch_data 退出码: " + $LASTEXITCODE)

# 2) 排行榜 + 基本面 + LLM 研报（已有报告自动跳过，节省 API 费用）
& $py -m src.build_ranking *>> $logFile
Write-Log ("build_ranking 退出码: " + $LASTEXITCODE)

# 3) 模拟盘绩效记录（按数据实际交易日去重覆盖，修正前一交易日的美股部分）
& $py tools\paper_portfolio.py report *>> $logFile
Write-Log ("paper_portfolio 退出码: " + $LASTEXITCODE)

# 4) 提交并推送数据（仅当有变化）
git add docs/data
if (-not (git diff --cached --quiet)) {
    $tradeDate = Get-Date -Format "yyyy-MM-dd"
    git commit -m ("chore(data): morning US catch-up for " + $tradeDate) *>> $logFile
    if ($LASTEXITCODE -eq 0) {
        git push origin main *>> $logFile
        Write-Log ("已推送 GitHub，退出码: " + $LASTEXITCODE)
    } else {
        Write-Log "提交失败：请先运行质量门禁 small（源码有变化时）"
    }
} else {
    Write-Log "数据无变化，跳过提交"
}

Write-Log "=== 完成 ==="
