param(
    [int]$IntervalSeconds = 120,
    [string]$ConfigPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

$args = @(
    "run",
    "bridgecal",
    "sync",
    "--daemon",
    "--interval",
    $IntervalSeconds.ToString()
)

if (-not [string]::IsNullOrWhiteSpace($ConfigPath)) {
    $args += @("--config", $ConfigPath)
}

& uv @args
exit $LASTEXITCODE
