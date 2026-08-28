# tools/install_daily_scheduler.ps1 —— 注册/卸载 Windows 定时任务计划（每日 15:30 自动长跑）
param(
    [switch]$Uninstall
)

$TaskName = "RainbowFinGPT_DailyRoutine"
$ScriptPath = Join-Path $PSScriptRoot "daily_live.ps1"
$PowerShellPath = (Get-Command powershell.exe).Source

if ($Uninstall) {
    Write-Host "正在卸载 Windows 计划任务: $TaskName ..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "✅ 计划任务已成功移除！" -ForegroundColor Green
    return
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "⏰ 正在注册 Rainbow-FinGPT 每日自动化无人值守长跑任务" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan

$Action = New-ScheduledTaskAction -Execute $PowerShellPath -Argument "-NoProfile -ExecutionPolicy Bypass -File "$ScriptPath""
$Trigger = New-ScheduledTaskTrigger -Daily -At "15:30"
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Rainbow-FinGPT 每日 15:30 自动执行大模型研报分析与策略调仓长跑" -Force

Write-Host "
✅ 计划任务注册成功！" -ForegroundColor Green
Write-Host "• 任务名称: $TaskName" -ForegroundColor Cyan
Write-Host "• 执行周期: 每日 15:30 (A股收盘后自动运行)" -ForegroundColor Cyan
Write-Host "• 执行脚本: $ScriptPath" -ForegroundColor Cyan
Write-Host "
💡 若需取消自动长跑，可随时运行: powershell tools/install_daily_scheduler.ps1 -Uninstall" -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Green
