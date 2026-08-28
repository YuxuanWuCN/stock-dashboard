[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$gitDirectory = Join-Path $projectRoot '.git'

if (-not (Test-Path -LiteralPath $gitDirectory)) {
    [Console]::Error.WriteLine('Git hooks were not installed because this directory is not a Git repository.')
    exit 2
}

& git -C $projectRoot config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine('Failed to configure core.hooksPath.')
    exit $LASTEXITCODE
}

$configured = & git -C $projectRoot config --get core.hooksPath
if ($LASTEXITCODE -ne 0 -or $configured.Trim() -ne '.githooks') {
    [Console]::Error.WriteLine('Git hook verification failed.')
    exit 2
}

Write-Output 'Git quality hooks are installed: core.hooksPath=.githooks'


