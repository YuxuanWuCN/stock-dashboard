# weekly_calibration.ps1 —— 周日晚上统一校准分析
#
# 功能：
# 1. 检查是否满足校准条件（≥3 个交易日）
# 2. 生成详细校准报告
# 3. 如果有验证期数据，同时生成验证报告
# 4. 发送通知或邮件提醒
#
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File tools\weekly_calibration.ps1
# 推荐：在 Windows 任务计划程序中设置为每周日 20:00 运行

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# 强制 UTF-8 编码（解决中文乱码问题）
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null  # 设置控制台代码页为 UTF-8

$py = Join-Path $repo ".venv\Scripts\python.exe"
$logFile = Join-Path $repo ".quality-state\weekly_calibration.log"

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Output $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

Write-Log "=== 周日校准分析开始 ==="
Write-Log ("当前日期: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))

# 1) 生成校准报告
Write-Log "步骤 1/3: 生成校准报告..."
& $py tools\calibration.py *>> $logFile
$calibrationExitCode = $LASTEXITCODE
Write-Log ("calibration.py 退出码: " + $calibrationExitCode)

if ($calibrationExitCode -eq 0) {
    Write-Log "✅ 校准报告已生成"

    # 2) 如果有验证期数据，生成验证报告
    Write-Log "步骤 2/3: 检查是否可生成验证报告..."
    & $py tools\verify_calibration.py *>> $logFile
    $verifyExitCode = $LASTEXITCODE
    Write-Log ("verify_calibration.py 退出码: " + $verifyExitCode)

    if ($verifyExitCode -eq 0) {
        Write-Log "✅ 验证报告已生成"
    } else {
        Write-Log "ℹ️  验证报告未生成（数据不足或未调参）"
    }

    # 3) 发送通知
    Write-Log "步骤 3/3: 发送通知..."
    $reportDir = Join-Path $repo "reports\calibration"
    $latestReport = Get-ChildItem -Path $reportDir -Filter "calibration_report_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

    if ($latestReport) {
        Write-Log ("📊 最新校准报告: " + $latestReport.Name)
        Write-Log "⚠️  请审核报告后，运行以下命令应用调参："
        Write-Log "    python tools\apply_calibration.py"

        # 可选：发送邮件通知（需配置 SMTP）
        # Send-MailMessage -To "your@email.com" -From "bot@example.com" -Subject "FinGPT 校准报告已生成" -Body "请查看: $($latestReport.FullName)" -SmtpServer "smtp.example.com"
    }

} elseif ($calibrationExitCode -eq 1) {
    Write-Log "⏸️  未满足校准触发条件（需要 ≥3 个交易日）"
} else {
    Write-Log "❌ 校准分析失败，请检查日志"
}

Write-Log "=== 周日校准分析完成 ==="

# 4) 策略进化分析（在校准之后）
Write-Log ""
Write-Log "=== 策略进化分析开始 ==="
& $py tools\weekly_champion_analysis.py *>> $logFile
$evolutionExitCode = $LASTEXITCODE
Write-Log ("weekly_champion_analysis 退出码: " + $evolutionExitCode)

if ($evolutionExitCode -eq 0) {
    Write-Log "✅ 策略进化分析完成"
    Write-Log "📊 本周冠军策略已选出，衍生策略已生成"
} else {
    Write-Log "ℹ️  策略进化分析未完成（数据不足或出错）"
}

Write-Log "=== 策略进化分析完成 ==="

# 输出摘要到控制台
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "📊 FinGPT 周日校准分析摘要" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($calibrationExitCode -eq 0) {
    Write-Host "✅ 校准报告已生成" -ForegroundColor Green
    Write-Host "📄 报告位置: reports\calibration\" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "📌 下一步操作:" -ForegroundColor Yellow
    Write-Host "   1. 查看校准报告: reports\calibration\calibration_report_*.json"
    Write-Host "   2. 审核调参建议"
    Write-Host "   3. 应用调参: python tools\apply_calibration.py"
    Write-Host ""
} else {
    Write-Host "⏸️  暂无校准报告（等待更多交易日数据）" -ForegroundColor Yellow
}

if ($evolutionExitCode -eq 0) {
    Write-Host "✅ 策略进化分析已完成" -ForegroundColor Green
    Write-Host "📄 报告位置: reports\strategy_evolution\" -ForegroundColor Yellow
    Write-Host "🧬 下周将运行 9 个组合（6基础 + 3衍生）" -ForegroundColor Cyan
    Write-Host ""
}

Write-Host "📝 详细日志: $logFile" -ForegroundColor Gray
Write-Host ""
