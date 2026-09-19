# =============================================================================
# tools/fetch_csmar_bc_trd_dalyr.ps1
#
# 用途：为本机拉取 B/C 两组（各 100 支）2024-01-02 ~ 2026-08-28 的 CSMAR
#       TRD_Dalyr 日频行情明细，用于补齐 master 面板中 B/C 组缺失的技术因子
#       （mom/vol/turnover_20d/amihud/price_pos/amplitude/gap/hit_limit/
#       abnormal_trd/ret）。供 M4 走步评测扩域（B、C）使用。
#
# 运行方式（交互式，缺什么填什么）：
#   powershell -ExecutionPolicy Bypass -File tools\fetch_csmar_bc_trd_dalyr.ps1
#   powershell -ExecutionPolicy Bypass -File tools\fetch_csmar_bc_trd_dalyr.ps1 -Smoke   # 每组先试跑 3 支，验证账号与额度
#
# 需要填写的东西（脚本会逐项提示并写入仓库 .env，.env 已被 .gitignore 忽略）：
#   1. CSMAR_SDK_PATH   ：CSMAR 官方 Python SDK（csmarapi 文件夹）所在目录。
#                         若未下载：CSMAR 数据平台个人中心 -> API 下载 SDK zip，
#                         解压后把路径填到包含 csmarapi 子目录的那一层。
#   2. CSMAR_USERNAME   ：CSMAR 个人账号。
#   3. CSMAR_PASSWORD   ：CSMAR 密码（明文存入本机 .env，仅供 SDK 登录使用）。
#
# 断点续拉：原始行情按“每批 10 支”缓存到 data/_raw_cache/。若当日下载额度
# 用尽导致中途失败，直接重跑本脚本即可——已缓存批次不会再消耗额度。
# 脚本本身不做任何数据改写，真实源表落盘后由既有 Python 管线完成校验与落盘。
# =============================================================================

[CmdletBinding()]
param(
    # 每组只试跑前 N 支，验证账号、SDK 与额度是否可用（默认关闭）
    [switch]$Smoke,
    # 跳过交互填写，直接使用现有 .env（用于额度用尽后的续拉）
    [switch]$NoPrompt
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'
$builder = Join-Path $projectRoot 'scripts\build_csmar_daily_panel_factors.py'

function Write-Step([string]$Message) { Write-Host "`n=== $Message ===" -ForegroundColor Cyan }
function Write-Ok([string]$Message)   { Write-Host "  [OK] $Message" -ForegroundColor Green }
function Write-Warn2([string]$Message){ Write-Host "  [!] $Message" -ForegroundColor Yellow }

# ------------------------------------------------------------- 1. 找 Python
# 要求候选解释器同时具备 pandas + numpy + csmarapi（build_daily_panel 的运行时）。
# csmar-python venv（含官方 SDK 与 pandas/numpy）优先；项目 py -3 缺 csmarapi 会自动跳过。
Write-Step '1/4 选择 Python 解释器（需 pandas+numpy+csmarapi 齐备）'
$cfg = @{}
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#') -or -not $t.Contains('=')) { continue }
        $k, $v = $t -split '=', 2
        $cfg[$k.Trim()] = $v.Trim().Trim('"').Trim("'")
    }
}

$candidates = @()
if ($cfg['CSMAR_PYTHON']) { $candidates += $cfg['CSMAR_PYTHON'] }
$knownVenv = 'C:\Users\34721\Documents\Codex\2026-09-07\ban\work\csmar-python\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $knownVenv) { $candidates += $knownVenv }
$repoVenv = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $repoVenv) { $candidates += $repoVenv }
$pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
if ($pyLauncher) { $candidates += "$($pyLauncher.Source) -3" }
$sysPython = (Get-Command 'python.exe' -ErrorAction SilentlyContinue).Source
if ($sysPython) { $candidates += $sysPython }

$checkCode = @'
import importlib, os, sys
sdk = os.environ.get('CSMAR_SDK_PATH', '')
if sdk:
    sys.path.insert(0, sdk)
missing = []
for module in ('pandas', 'numpy'):
    try:
        importlib.import_module(module)
    except Exception:
        missing.append(module)
try:
    importlib.import_module('csmarapi.CsmarService')
except Exception:
    missing.append('csmarapi')
print('MISSING:' + ','.join(missing) if missing else 'READY')
'@
$checkFile = Join-Path $env:TEMP 'csmar_python_check.py'
Set-Content -Path $checkFile -Value $checkCode -Encoding UTF8
$env:CSMAR_SDK_PATH = $cfg['CSMAR_SDK_PATH']

$python = $null
foreach ($candidate in $candidates) {
    $parts = $candidate -split ' '
    $missing = & $parts[0] $parts[1..($parts.Length - 1)] $checkFile 2>$null
    if ($LASTEXITCODE -eq 0 -and "$missing" -eq 'READY') { $python = $candidate; break }
    Write-Warn2 "跳过 $candidate（缺 $missing）"
}
if (-not $python) {
    throw "没有同时具备 pandas+numpy+csmarapi 的解释器。请先运行 tools\verify_csmar_login.ps1 完成配置。"
}
Write-Ok "使用 Python：$python"

# ------------------------------------------------- 2/4. 读取 / 交互填写 .env
Write-Step '2/4 检查 CSMAR 配置（SDK 路径 + 账号）'
if (-not $NoPrompt) {
    if (-not $cfg['CSMAR_SDK_PATH']) {
        Write-Warn2 '未配置 CSMAR_SDK_PATH。'
        Write-Host  '  SDK = CSMAR 官网个人中心下载的 Python API（解压后含 csmarapi 文件夹）。'
        $input_ = Read-Host '  请输入 csmarapi 所在目录的完整路径（直接回车退出稍后再配）'
        if ($input_) { $cfg['CSMAR_SDK_PATH'] = $input_.Trim('"') }
    }
    if (-not $cfg['CSMAR_USERNAME']) { $cfg['CSMAR_USERNAME'] = (Read-Host '  请输入 CSMAR 用户名').Trim() }
    if (-not $cfg['CSMAR_PASSWORD']) {
        $sec = Read-Host '  请输入 CSMAR 密码' -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        $cfg['CSMAR_PASSWORD'] = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

$sdkPath  = $cfg['CSMAR_SDK_PATH']
$username = $cfg['CSMAR_USERNAME']
$password = $cfg['CSMAR_PASSWORD']

# SDK 路径兜底：仓库同级 csmar/sdk
if (-not $sdkPath) {
    $guess = Join-Path (Split-Path -Parent $projectRoot) 'csmar\sdk'
    if (Test-Path -LiteralPath (Join-Path $guess 'csmarapi')) { $sdkPath = $guess }
}

if ($sdkPath) {
    $svcFile = Join-Path $sdkPath 'csmarapi\CsmarService.py'
    if (-not (Test-Path -LiteralPath $svcFile)) {
        $alt = Join-Path $sdkPath 'CsmarService.py'
        if (Test-Path -LiteralPath $alt) {
            # 用户直接填了 csmarapi 的父目录名或更深层路径，向上找一层
            $sdkPath = Split-Path -Parent $sdkPath
        } else {
            throw "CSMAR_SDK_PATH=$sdkPath 下未找到 csmarapi\CsmarService.py，请检查路径。"
        }
    }
    Write-Ok "SDK 路径：$sdkPath"
} else {
    Write-Warn2 '缺少 SDK 路径：将从 CSMAR 数据平台个人中心下载 SDK 后重跑本脚本。'
}

if (-not $username -or -not $password) {
    throw '缺少 CSMAR_USERNAME / CSMAR_PASSWORD。重跑本脚本并按提示填写。'
}

# 写回 .env（含 SDK 路径与选中的解释器），供 Python 端 build_client() 与后续运行直接加载
$wanted = @{
    'CSMAR_SDK_PATH' = $sdkPath
    'CSMAR_USERNAME' = $username
    'CSMAR_PASSWORD' = $password
    'CSMAR_PYTHON'   = $python
}
$lines = @(Get-Content $envFile -Encoding UTF8 -ErrorAction SilentlyContinue | Where-Object {
    $t = $_.Trim(); $t -and -not $t.StartsWith('#') -and -not ($t -split '=', 2)[0].Trim().StartsWith('CSMAR_')
})
foreach ($k in $wanted.Keys) { if ($wanted[$k]) { $lines += "$k=$($wanted[$k])" } }
Set-Content -Path $envFile -Value $lines -Encoding UTF8
Write-Ok "已写入 $envFile（该文件被 .gitignore 忽略，不会入库）"

# ---------------------------------------------------- 3/4. 拉取 B / C 两组
Write-Step '3/4 拉取 TRD_Dalyr（student_B -> student_C）'
$limitArgs = @()
if ($Smoke) {
    # Smoke 模式绝不写正式输出路径，避免半量面板被误当真实数据
    $limitArgs = @('--limit-codes', '3')
    Write-Warn2 'Smoke 模式：每组只取前 3 支（验证账号与额度，写入独立冒烟文件）。'
}

$pythonParts = $python -split ' '
foreach ($cohort in @('student_B', 'student_C')) {
    Write-Host "`n---- $cohort ----" -ForegroundColor Cyan
    $args_ = @($pythonParts[1..($pythonParts.Length - 1)]) + @($builder, '--cohort', $cohort) + $limitArgs
    if ($Smoke) {
        $args_ += @('--output', (Join-Path $projectRoot "data\task_split\smoke_factors_daily_panel_$cohort.csv"))
    }
    & $pythonParts[0] @args_
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "$cohort 拉取未完成（退出码 $LASTEXITCODE）。"
        Write-Host  '  常见原因：当日下载额度用尽 / 网络超时。已成功批次已缓存到 data/_raw_cache/，'
        Write-Host  '  直接重跑本脚本即可从断点继续，不会重复消耗额度。'
        exit $LASTEXITCODE
    }
}

# ---------------------------------------------------- 5. 校验落盘产物
Write-Step '4/4 校验产物'
if ($Smoke) {
    Write-Ok 'Smoke 试跑完成：账号、SDK、额度均可用。去掉 -Smoke 重跑即为正式拉取。'
    exit 0
}
$okAll = $true
foreach ($cohort in @('student_B', 'student_C')) {
    $out = Join-Path $projectRoot "data\task_split\factors_daily_panel_$cohort.csv"
    if (Test-Path -LiteralPath $out) {
        $rows = (Get-Content $out | Measure-Object -Line).Lines - 1
        Write-Ok "$out （$rows 行）"
    } else {
        Write-Warn2 "缺少 $out —— 拉取未成功，请查看上方日志。"
        $okAll = $false
    }
}
if ($okAll) {
    Write-Host "`n全部完成。下一步由工作区内的数据管线把 B/C 技术因子并入 master 面板并运行 M4 评测。" -ForegroundColor Green
} else {
    exit 1
}
