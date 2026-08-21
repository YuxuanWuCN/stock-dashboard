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
#
# 修复记录（2026-08-19）：改用 Start-Process 分离重定向 stdout/stderr，
# 避免 PowerShell 5.1 的 *>> 在大量 stderr 输出时把每行包装成 NativeCommandError
# 错误记录，导致 build_ranking 等后续命令启动失败/秒退、$LASTEXITCODE 读到残留值 0
# 的问题；同时每次调用后显式校验退出码并在失败时报警。

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:STOCK_PROXY = "direct"  # 直连模式：避免 Clash 代理导致连接失败
$env:LLM_DAILY_CALL_LIMIT = "800"
$py = Join-Path $repo ".venv\Scripts\python.exe"
$logFile = Join-Path $repo ".quality-state\daily_morning.log"
$runDir = Join-Path $repo ".quality-state\morning_runs"
if (-not (Test-Path $runDir)) { New-Item -ItemType Directory -Path $runDir -Force | Out-Null }

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Output $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

# 运行一个 Python 步骤：分离 stdout/stderr 重定向，返回真实退出码
function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$StepArgs
    )
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $outFile = Join-Path $runDir ($Name + "_" + $stamp + ".out.log")
    $errFile = Join-Path $runDir ($Name + "_" + $stamp + ".err.log")
    $proc = Start-Process -FilePath $py -ArgumentList $StepArgs -NoNewWindow -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $proc.WaitForExit()
    $code = $proc.ExitCode
    if (Test-Path $errFile) {
        $errLines = Get-Content $errFile -Tail 30 -Encoding UTF8 -ErrorAction SilentlyContinue
        foreach ($l in $errLines) { Add-Content -Path $logFile -Value $l -Encoding UTF8 }
    }
    if (Test-Path $outFile) {
        $outLines = Get-Content $outFile -Tail 10 -Encoding UTF8 -ErrorAction SilentlyContinue
        foreach ($l in $outLines) { Add-Content -Path $logFile -Value $l -Encoding UTF8 }
    }
    Write-Log ("{0} 退出码: {1}" -f $Name, $code)
    if ($code -ne 0) {
        Write-Log ("⚠️  {0} 失败（退出码 {1}），请检查 {2}" -f $Name, $code, $errFile)
    }
    return $code
}

Write-Log "=== 早上美股补数据开始 ==="

# 1) 抓取行情（美股补上昨日收盘；A股/港股无新数据时保持原样）
Invoke-Step -Name "fetch_data" -StepArgs @("-m", "src.fetch_data")

# 2) 排行榜 + 基本面 + LLM 研报（已有报告自动跳过，节省 API 费用）
Invoke-Step -Name "build_ranking" -StepArgs @("-m", "src.build_ranking")

# 3) 模拟盘绩效记录（按数据实际交易日去重覆盖，修正前一交易日的美股部分）
Invoke-Step -Name "paper_portfolio_report" -StepArgs @("tools\paper_portfolio.py", "report")
# 3.x) 全池等权基准对照组（全部自选股买入持有，累计净值曲线）
Invoke-Step -Name "paper_portfolio_benchmark" -StepArgs @("tools\paper_portfolio.py", "benchmark")
# 3.y) 生成模拟盘组合清单（前端动态展示全部组合）
Invoke-Step -Name "paper_portfolio_manifest" -StepArgs @("tools\paper_portfolio.py", "manifest")

# 3.z) 美股补数后刷新历史快照与随机对照（协议 v1：每日积累统计样本）
Invoke-Step -Name "reconstruct_summary" -StepArgs @("tools\reconstruct_summary.py", "--all")
Invoke-Step -Name "random_control" -StepArgs @("tools\random_control.py")
Invoke-Step -Name "market_benchmark" -StepArgs @("tools\market_benchmark.py")

# 4) 提交并推送数据（仅当有变化；GitHub 直连失败时自动走本机代理重试）
git add docs/data
if (-not (git diff --cached --quiet)) {
    $tradeDate = Get-Date -Format "yyyy-MM-dd"
    git commit -m ("chore(data): morning US catch-up for " + $tradeDate) *>> $logFile
    if ($LASTEXITCODE -eq 0) {
        Invoke-Step -Name "git_push" -StepArgs @("tools\git_push_with_fallback.py")
    } else {
        Write-Log "提交失败：请先运行质量门禁 small（源码有变化时）"
    }
} else {
    Write-Log "数据无变化，跳过提交"
}

Write-Log "=== 完成 ==="
