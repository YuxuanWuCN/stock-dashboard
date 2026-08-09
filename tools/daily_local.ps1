# daily_local.ps1 —— 每日本地数据更新（替代 GitHub Actions 云端爬取）
#
# 流程：抓取行情 → 排行榜+基本面+LLM研报 → 策略/市场温度 → 提交推送 GitHub
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File tools\daily_local.ps1

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:STOCK_PROXY = "direct"  # 直连模式：避免 Clash 代理导致东财连接失败
$env:LLM_DAILY_CALL_LIMIT = "400"  # 全量生成22只AI报告需要更多API调用额度
$py = Join-Path $repo ".venv\Scripts\python.exe"
$logFile = Join-Path $repo ".quality-state\daily_local.log"

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Output $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

Write-Log "=== 每日本地数据更新开始 ==="

# 1) 抓取行情（K线 + summary + 场外基金净值）
& $py -m src.fetch_data *>> $logFile
Write-Log ("fetch_data 退出码: " + $LASTEXITCODE)

# 2) 排行榜 + 基本面 + LLM 研报（已有报告自动跳过，节省 API 费用）
& $py -m src.build_ranking *>> $logFile
Write-Log ("build_ranking 退出码: " + $LASTEXITCODE)

# 3) 策略选股 + 狩猎场 + 市场温度
& $py -m src.strategies.main --scope watchlist *>> $logFile
Write-Log ("strategies 退出码: " + $LASTEXITCODE)

# 3.5) 明日重点关注 AI 总结（DeepSeek 本地调用，失败不影响主流程）
& $py -m src.strategies.daily_brief *>> $logFile
Write-Log ("daily_brief 退出码: " + $LASTEXITCODE)
# 4) 提交并推送数据（仅当有变化）
git add docs/data
if (-not (git diff --cached --quiet)) {
    $tradeDate = Get-Date -Format "yyyy-MM-dd"
    git commit -m ("chore(data): update dashboard data for " + $tradeDate) *>> $logFile
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