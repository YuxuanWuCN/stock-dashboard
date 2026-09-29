# =============================================================================
# tools/verify_csmar_login.ps1 —— CSMAR 一条命令配置 + 登录验证
#
# 与手动验证命令同款（venv Python + csmarapi 登录 + getListDbs 计数），额外把
# 凭据自动写入仓库 .env（密码经 getpass 输入，不回显、不进命令行、不打印），
# 之后 tools/fetch_csmar_bc_trd_dalyr.ps1 以 -NoPrompt 直接续跑。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\verify_csmar_login.ps1
#   powershell -ExecutionPolicy Bypass -File tools\verify_csmar_login.ps1 -Python "自定义venv\python.exe"
# =============================================================================

[CmdletBinding()]
param(
    # 可指定 csmar venv 的 python.exe；缺省自动探测 csmar-python 工作目录
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'

# ---------------------------------------------------------------- 1. 找 venv Python
$candidates = @(
    $Python,
    $env:CSMAR_PYTHON,
    'C:\Users\34721\Documents\Codex\2026-09-07\ban\work\csmar-python\.venv\Scripts\python.exe'
)
$venvPython = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $venvPython) {
    throw "未找到 csmar venv 的 python.exe。请用 -Python 参数指定，例如：`n" +
          '  -Python "C:\Users\34721\Documents\Codex\2026-09-07\ban\work\csmar-python\.venv\Scripts\python.exe"'
}
Write-Host "[1/3] 使用 venv Python：$venvPython" -ForegroundColor Cyan

# ---------------------------------------------------------------- 2. 登录验证 + 写 .env
Write-Host '[2/3] 请输入 CSMAR 账号与密码（密码不回显），随后调用 getListDbs 验证登录…' -ForegroundColor Cyan

$inner = @'
import os, sys
from pathlib import Path
from getpass import getpass
repo = os.environ['REPO_ROOT']
sys.path.insert(0, os.environ['SDK_SITE_PACKAGES'])
try:
    from csmarapi.CsmarService import CsmarService
except Exception as exc:
    print(f'SDK 导入失败：{exc}'); sys.exit(2)
account = input('CSMAR账号：').strip()
password = getpass('CSMAR密码：').strip()
svc = CsmarService()
svc.login(account, password, '0')
dbs = svc.getListDbs()
print('登录验证完成，数据库数量：', len(dbs) if dbs else 0)
env_path = Path(repo) / '.env'
lines = []
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in line:
            continue
        key = line.split('=', 1)[0].strip()
        if key.startswith('CSMAR_'):
            continue
        lines.append(line.rstrip())
lines += [
    f'CSMAR_USERNAME={account}',
    f'CSMAR_PASSWORD={password}',
    f'CSMAR_PYTHON={os.environ["VENV_PYTHON"]}',
    f'CSMAR_SDK_PATH={os.environ["SDK_SITE_PACKAGES"]}',
]
env_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print('已写入', env_path, '（.gitignore 已忽略，不会入库）')
'@

$probe = Join-Path $env:TEMP 'csmar_login_verify.py'
Set-Content -Path $probe -Value $inner -Encoding UTF8
$sitePackages = Split-Path -Parent (Split-Path -Parent $venvPython)
$env:REPO_ROOT = $projectRoot
$env:VENV_PYTHON = $venvPython
$env:SDK_SITE_PACKAGES = Join-Path $sitePackages 'Lib\site-packages'
& $venvPython $probe
if ($LASTEXITCODE -ne 0) {
    Remove-Item $probe -ErrorAction SilentlyContinue
    throw "登录验证失败（退出码 $LASTEXITCODE）。请检查账号、密码或网络后重试。"
}

# ---------------------------------------------------------------- 3. 完成
Remove-Item $probe -ErrorAction SilentlyContinue
Write-Host '[3/3] 配置完成。下一步：' -ForegroundColor Green
Write-Host '  powershell -ExecutionPolicy Bypass -File tools\fetch_csmar_bc_trd_dalyr.ps1 -Smoke   # 试跑 3 支'
Write-Host '  powershell -ExecutionPolicy Bypass -File tools\fetch_csmar_bc_trd_dalyr.ps1          # 正式拉取 B/C 各 100 支'
