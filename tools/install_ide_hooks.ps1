# 安装 IDE 门禁 hook（彩虹找虫 v2）
# 用法: powershell -ExecutionPolicy Bypass -File tools/install_ide_hooks.ps1 [-Ide claude|codex|all]
# 与 install_hooks.ps1（git hooksPath）职责分离：本脚本只装 IDE 工具调用 hook。

[CmdletBinding()]
param(
    [ValidateSet('claude', 'codex', 'all')]
    [string]$Ide = 'all'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

# Python 解释器回退链（与 run_quality.ps1 一致）
$candidates = New-Object System.Collections.Generic.List[object]
if ($env:QUALITY_GATE_PYTHON) {
    $candidates.Add([PSCustomObject]@{ Executable = $env:QUALITY_GATE_PYTHON; Prefix = @() })
}
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $projectPython) {
    $candidates.Add([PSCustomObject]@{ Executable = $projectPython; Prefix = @() })
}
$pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $candidates.Add([PSCustomObject]@{ Executable = $pyLauncher.Source; Prefix = @('-3') })
}
$pythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
if ($pythonCommand) {
    $candidates.Add([PSCustomObject]@{ Executable = $pythonCommand.Source; Prefix = @() })
}

$selected = $null
foreach ($candidate in $candidates) {
    try {
        & $candidate.Executable @($candidate.Prefix) --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $selected = $candidate
            break
        }
    }
    catch {
        continue
    }
}
if (-not $selected) {
    [Console]::Error.WriteLine('Cannot install IDE hooks: Python 3 was not found.')
    exit 127
}

$ideList = @()
if ($Ide -eq 'all') { $ideList = @('claude', 'codex') }
else { $ideList = @($Ide) }

foreach ($ide in $ideList) {
    Write-Output "Installing $ide hooks..."
    & $selected.Executable @($selected.Prefix) "$projectRoot\tools\ide_registry.py" install --ide $ide --root $projectRoot
    if ($LASTEXITCODE -ne 0) {
        [Console]::Error.WriteLine("Failed to install $ide hooks (exit $LASTEXITCODE)")
        exit $LASTEXITCODE
    }
}

Write-Output ''
Write-Output 'IDE hooks installed.'
Write-Output 'Note: Codex hooks need first-time trust approval via /hooks in Codex.'
Write-Output 'Note: Trae adapter is reserved but not implemented in v2.'
