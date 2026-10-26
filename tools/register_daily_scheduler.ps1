# register_daily_scheduler.ps1 —— 一键注册 Windows 每日盘后自动更新计划任务
#
# 功能：将工作日 17:30 (A股收盘后) 数据自动同步注册为 Windows 系统后台任务
# 任务名固定为 StockDashboard-DailyUpdate（与线上既有任务、文档一致）
# 可靠性：允许电池供电运行、用电池时不停机、关机错过后开机自动补跑、多实例忽略新触发
# 用法：以管理员身份或普通用户运行：powershell -ExecutionPolicy Bypass -File tools\register_daily_scheduler.ps1
# 注意：本文件以 UTF-8 with BOM 保存，PowerShell 5.1 才能正确显示中文。

$ErrorActionPreference = "Stop"
$TaskName = "StockDashboard-DailyUpdate"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $RepoRoot "tools\daily_local.ps1"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Rainbow FinGPT 每日自动更新计划任务安装器" -ForegroundColor Cyan
Write-Host "=========================================================="

if (-not (Test-Path $ScriptPath)) {
    Write-Error "未找到更新脚本: $ScriptPath"
    exit 1
}

# 1. 检查是否存在既有任务并清理
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[i] 检测到已存在计划任务 [$TaskName]，正在按 17:30 重新配置..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 2. 创建触发器：每周一至周五 17:30:00 (A股收盘与结算后)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 17:30

# 3. 创建动作：后台静默拉起 PowerShell 运行 daily_local.ps1
$actionArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs -WorkingDirectory $RepoRoot

# 4. 配置任务属性：允许电池供电运行、用电池时不停机、错失后尽快补跑、忽略并发新实例
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

# 5. 注册计划任务 (当前用户权限)
try {
    $null = Register-ScheduledTask -TaskName $TaskName -Trigger $trigger -Action $action -Settings $settings -Description "Rainbow FinGPT 盘后每日全自动数据更新与量化指标计算（工作日 17:30，允许电池供电与错过后补跑）"
    Write-Host ""
    Write-Host "[OK] 成功注册 Windows 每日自动更新计划任务！" -ForegroundColor Green
    Write-Host "   - 任务名称: $TaskName" -ForegroundColor Gray
    Write-Host "   - 执行周期: 每周一至周五 17:30 (A股盘后)" -ForegroundColor Gray
    Write-Host "   - 执行脚本: $ScriptPath" -ForegroundColor Gray
    Write-Host "   - 可靠性: 允许电池供电 / 电池上不停机 / 错过后开机自动补跑" -ForegroundColor Gray
    Write-Host ""
    Write-Host "[i] 如需卸载该定时任务，随时运行 tools\unregister_daily_scheduler.ps1 即可。" -ForegroundColor Cyan
} catch {
    Write-Host ""
    Write-Host "[!] Register-ScheduledTask 失败，回退使用 schtasks 注册..." -ForegroundColor Yellow
    # 回退：schtasks 无法直接表达"电池供电"，注册后仍需用 Set-ScheduledTask 加固电源设置
    & schtasks.exe /Create /TN $TaskName /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 17:30 /F
    if ($LASTEXITCODE -ne 0) { throw "schtasks 注册失败，退出码 $LASTEXITCODE" }

    $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
    $null = Set-ScheduledTask -TaskName $TaskName -Settings $s
    Write-Host "[OK] 已通过 schtasks 完成注册，并补齐电池供电/补跑设置。" -ForegroundColor Green
}
