# register_daily_scheduler.ps1 —— 一键注册 Windows 每日盘后自动更新计划任务
#
# 功能：将工作日 17:30 (A股收盘后) 数据自动同步注册为 Windows 系统后台任务
# 用法：以管理员身份或普通用户运行：powershell -ExecutionPolicy Bypass -File tools\register_daily_scheduler.ps1

$ErrorActionPreference = "Stop"
$TaskName = "RainbowFinGPT_DailyUpdate"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $RepoRoot "tools\daily_local.ps1"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Rainbow FinGPT 每日自动更新计划任务安装器" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

if (-not (Test-Path $ScriptPath)) {
    Write-Error "❌ 未找到更新脚本: $ScriptPath"
    exit 1
}

# 1. 检查是否存在既有任务并清理
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "ℹ️ 检测到已存在计划任务 [$TaskName]，正在更新..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 2. 创建触发器：每周一至周五 17:30:00 (A股收盘与结算后)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 17:30

# 3. 创建动作：后台静默拉起 PowerShell 运行 daily_local.ps1
$actionArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs -WorkingDirectory $RepoRoot

# 4. 配置任务属性：允许按需运行、错失后尽快补跑
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

# 5. 注册计划任务 (当前用户权限)
try {
    $task = Register-ScheduledTask -TaskName $TaskName -Trigger $trigger -Action $action -Settings $settings -Description "Rainbow FinGPT 盘后每日全自动数据更新与量化指标计算"
    Write-Host "`n✅ 成功注册 Windows 每日自动更新计划任务！" -ForegroundColor Green
    Write-Host "   • 任务名称: $TaskName" -ForegroundColor Gray
    Write-Host "   • 执行周期: 每周一至周五 17:30 (A股盘后)" -ForegroundColor Gray
    Write-Host "   • 执行脚本: $ScriptPath" -ForegroundColor Gray
    Write-Host "   • 容错机制: 若当时未开机，将在开机后自动自检补漏" -ForegroundColor Gray
    Write-Host "`n💡 如需卸载该定时任务，随时运行 tools\unregister_daily_scheduler.ps1 即可。" -ForegroundColor Cyan
} catch {
    Write-Host "`n⚠️ 注册任务时出现权限提示，尝试以当前用户交互模式注册..." -ForegroundColor Yellow
    schtasks.exe /Create /TN $TaskName /TR "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 17:30 /F
    Write-Host "✅ 已通过 schtasks 完成注册！" -ForegroundColor Green
}
