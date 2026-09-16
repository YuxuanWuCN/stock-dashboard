# unregister_daily_scheduler.ps1 —— 卸载 Windows 每日自动更新计划任务
#
# 功能：安全卸载已注册的 RainbowFinGPT_DailyUpdate 计划任务
# 用法：powershell -ExecutionPolicy Bypass -File tools\unregister_daily_scheduler.ps1

$ErrorActionPreference = "SilentlyContinue"
$TaskName = "RainbowFinGPT_DailyUpdate"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Rainbow FinGPT 计划任务卸载器" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "✅ 成功卸载 Windows 计划任务: $TaskName" -ForegroundColor Green
} else {
    schtasks.exe /Delete /TN $TaskName /F > $null 2>&1
    Write-Host "ℹ️ 计划任务 $TaskName 已不存在或已清理完毕。" -ForegroundColor Yellow
}
