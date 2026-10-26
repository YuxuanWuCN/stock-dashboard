# unregister_daily_scheduler.ps1 —— 卸载 Windows 每日自动更新计划任务
#
# 功能：安全卸载已注册的 StockDashboard-DailyUpdate 计划任务
# 用法：powershell -ExecutionPolicy Bypass -File tools\unregister_daily_scheduler.ps1
# 注意：本文件以 UTF-8 with BOM 保存，PowerShell 5.1 才能正确显示中文。

$ErrorActionPreference = "SilentlyContinue"
$TaskName = "StockDashboard-DailyUpdate"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Rainbow FinGPT 计划任务卸载器" -ForegroundColor Cyan
Write-Host "=========================================================="

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] 成功卸载 Windows 计划任务: $TaskName" -ForegroundColor Green
} else {
    $null = schtasks.exe /Delete /TN $TaskName /F 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] 已通过 schtasks 清理计划任务: $TaskName" -ForegroundColor Green
    } else {
        Write-Host "[i] 计划任务 $TaskName 已不存在或已清理完毕。" -ForegroundColor Yellow
    }
}
