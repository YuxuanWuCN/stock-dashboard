# daily_local.ps1 —— 每日本地全自动数据更新与量化流水线
#
# 功能：自动检测 Python 环境并启动统一量化自动化调度引擎（tools/daily_routine.py）
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File tools\daily_local.ps1

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# 强制 UTF-8 编码
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

# 自动寻找 Python 可执行文件
$candidates = @(
    (Join-Path $repo ".venv\Scripts\python.exe"),
    "python.exe",
    "py.exe"
)

$py = $null
foreach ($c in $candidates) {
    if (Test-Path $c -ErrorAction SilentlyContinue) {
        $py = $c
        break
    }
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) {
        $py = $cmd.Source
        break
    }
}

if (-not $py) {
    Write-Error "❌ 未找到 Python 环境，请检查 PATH 或激活虚拟环境。"
    exit 1
}

Write-Host "🌟 使用 Python 解释器: $py" -ForegroundColor Cyan
& $py tools\daily_routine.py @args
exit $LASTEXITCODE
