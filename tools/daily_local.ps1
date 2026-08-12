# daily_local.ps1 —— 每日本地数据更新（替代 GitHub Actions 云端爬取）
#
# 流程：抓取行情 → 排行榜+基本面+LLM研报 → 策略/市场温度 → 提交推送 GitHub
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File tools\daily_local.ps1

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# 强制 UTF-8 编码（解决中文乱码问题）
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null  # 设置控制台代码页为 UTF-8

$env:STOCK_PROXY = "direct"  # 直连模式：避免 Clash 代理导致东财连接失败
$env:LLM_DAILY_CALL_LIMIT = "800"  # 202只自选股AI研报增量生成额度（防截断）
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

# 3.6) 每日市场情绪分析（🆕 使用 DeepSeek v4-flash 分析）
& $py tools\daily_market_sentiment.py *>> $logFile
Write-Log ("market_sentiment 退出码: " + $LASTEXITCODE)

# 3.7) 模拟盘组合绩效记录（对比组合 vs 等权基准）—— 先记录今日绩效（使用旧持仓）
& $py tools\paper_portfolio.py report *>> $logFile
Write-Log ("paper_portfolio 退出码: " + $LASTEXITCODE)

# 3.7) 所有组合自动调仓（在绩效记录之后，为明日选股）
& $py tools\rebalance_all_portfolios.py *>> $logFile
Write-Log ("rebalance_all_portfolios 退出码: " + $LASTEXITCODE)
# 3.8) 全池等权基准对照组（全部自选股买入持有，累计净值曲线）
& $py tools\paper_portfolio.py benchmark *>> $logFile
Write-Log ("paper_portfolio benchmark 退出码: " + $LASTEXITCODE)
# 3.9) 生成模拟盘组合清单（前端动态展示全部组合）
& $py tools\paper_portfolio.py manifest *>> $logFile
Write-Log ("paper_portfolio manifest 退出码: " + $LASTEXITCODE)

# 3.10) 同步量化数据到 Dashboard（供 portfolio.html 展示）
Write-Log "同步量化数据到 Dashboard..."
$dashboardDataDir = Join-Path $repo "..\\.upload-stock-dashboard\docs\data\quantitative"
if (-not (Test-Path $dashboardDataDir)) {
    New-Item -ItemType Directory -Path $dashboardDataDir -Force | Out-Null
}

# 复制6组合表现数据
Get-ChildItem "docs\data\paper\performance_*.json" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName -Destination $dashboardDataDir -Force
    Write-Log ("  复制: " + $_.Name)
}

# 复制最新市场情绪数据
$latestSentiment = Get-ChildItem "reports\market_sentiment\sentiment_*.json" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latestSentiment) {
    Copy-Item $latestSentiment.FullName -Destination (Join-Path $dashboardDataDir "latest_sentiment.json") -Force
    Write-Log ("  复制: " + $latestSentiment.Name + " → latest_sentiment.json")
}

# 复制最新策略进化数据（先转换为前端格式，兼容 portfolio.js 的扁平字段）
& $py tools\weekly_champion_analysis.py export *>> $logFile
Write-Log ("weekly_champion export 退出码: " + $LASTEXITCODE)
$latestEvolution = Get-ChildItem "reports\strategy_evolution\latest_evolution.json" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latestEvolution) {
    Copy-Item $latestEvolution.FullName -Destination (Join-Path $dashboardDataDir "latest_evolution.json") -Force
    Write-Log ("  复制: " + $latestEvolution.Name + " → latest_evolution.json")
}

Write-Log "Dashboard 数据同步完成"

# 3.z) FinGPT 后训练校准检查（≥3 个交易日时自动生成校准报告）
& $py tools\calibration.py *>> $logFile
$calibrationExitCode = $LASTEXITCODE
Write-Log ("calibration check 退出码: " + $calibrationExitCode)
if ($calibrationExitCode -eq 0) {
    Write-Log "⚠️  校准报告已生成，请审核后运行 python tools\apply_calibration.py"
}

# 4) 提交并推送数据（仅当有变化；GitHub 直连失败时自动走本机代理重试）
git add docs/data
if (-not (git diff --cached --quiet)) {
    $tradeDate = Get-Date -Format "yyyy-MM-dd"
    git commit -m ("chore(data): update dashboard data for " + $tradeDate) *>> $logFile
    if ($LASTEXITCODE -eq 0) {
        & $py tools\git_push_with_fallback.py *>> $logFile
        Write-Log ("GitHub 推送退出码: " + $LASTEXITCODE)
    } else {
        Write-Log "提交失败：请先运行质量门禁 small（源码有变化时）"
    }
} else {
    Write-Log "数据无变化，跳过提交"
}

Write-Log "=== 完成 ==="
