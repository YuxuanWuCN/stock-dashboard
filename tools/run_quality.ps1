[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [string]$Command,

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArguments
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$qualityScript = Join-Path $PSScriptRoot 'quality_gate.py'
$gateArguments = @($Command) + @($RemainingArguments)

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

$codexPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $codexPython) {
    $candidates.Add([PSCustomObject]@{ Executable = $codexPython; Prefix = @() })
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
    [Console]::Error.WriteLine('Quality gate cannot run: Python 3 was not found. Install Python 3 or set QUALITY_GATE_PYTHON.')
    exit 127
}

$pythonArguments = @($selected.Prefix) + @($qualityScript) + $gateArguments
# 只对需要 stdin 的命令转发输入（BUG-0034）：git commit 的 pre-commit hook
# 运行时 stdin 是保持打开的管道，若在此 ReadToEnd() 会永久死锁。
$stdinCommands = @('verify-push', 'hook-pre', 'hook-pre-bash', 'hook-failure')
if ([Console]::IsInputRedirected -and ($stdinCommands -contains $Command)) {
    $inputText = [Console]::In.ReadToEnd()
    $inputText | & $selected.Executable @pythonArguments
}
else {
    & $selected.Executable @pythonArguments
}
exit $LASTEXITCODE
