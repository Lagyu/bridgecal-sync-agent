param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ConfigPath = (Join-Path $env:APPDATA "BridgeCal\config.toml"),
    [switch]$NoSync
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[BridgeCal GUI] $Message" -ForegroundColor Cyan
}

function Fail {
    param(
        [string]$Message,
        [int]$ExitCode = 1
    )
    Write-Error $Message
    exit $ExitCode
}

function Refresh-PathFromSystem {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")

    if ([string]::IsNullOrWhiteSpace($machinePath)) {
        $machinePath = ""
    }
    if ([string]::IsNullOrWhiteSpace($userPath)) {
        $userPath = ""
    }

    $joined = "$machinePath;$userPath".Trim(";")
    if (-not [string]::IsNullOrWhiteSpace($joined)) {
        $env:Path = $joined
    }
}

function Ensure-Winget {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        return
    }

    Fail "winget is required for automatic dependency installation. Install App Installer / winget first, then re-run."
}

function Install-WithWinget {
    param(
        [string]$PackageId,
        [string]$FriendlyName,
        [string]$Scope = "user",
        [string]$Override = ""
    )

    Write-Step "Installing $FriendlyName via winget ($PackageId)..."
    $args = @(
        "install",
        "--id", $PackageId,
        "-e",
        "--accept-source-agreements",
        "--accept-package-agreements"
    )
    if (-not [string]::IsNullOrWhiteSpace($Scope)) {
        $args += @("--scope", $Scope)
    }
    if (-not [string]::IsNullOrWhiteSpace($Override)) {
        $args += @("--override", $Override)
    }

    & winget @args
    return ($LASTEXITCODE -eq 0)
}

function Test-Python312 {
    try {
        & py -3.12 -c "import sys" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    } catch {
        # continue
    }

    try {
        $version = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
        if ([version]$version -ge [version]"3.12") {
            return $true
        }
    } catch {
        # continue
    }

    return $false
}

function Ensure-Python {
    if (Test-Python312) {
        return
    }

    Ensure-Winget
    $installed = Install-WithWinget -PackageId "Python.Python.3.12" -FriendlyName "Python 3.12"
    if (-not $installed) {
        $installed = Install-WithWinget -PackageId "Python.Python.3" -FriendlyName "Python 3"
    }

    Refresh-PathFromSystem
    if (-not (Test-Python312)) {
        Fail "Python install did not complete successfully. Install Python 3.12+ manually, then re-run this script."
    }
}

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        return
    }

    Ensure-Winget
    $installed = Install-WithWinget -PackageId "astral-sh.uv" -FriendlyName "uv"
    if (-not $installed) {
        try {
            Write-Step "winget install for uv failed; trying official installer..."
            Invoke-RestMethod "https://astral.sh/uv/install.ps1" | Invoke-Expression
            $installed = $true
        } catch {
            $installed = $false
        }
    }

    Refresh-PathFromSystem
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Fail "uv installation failed. Install uv manually, then re-run this script."
    }
}

function Test-BridgeCalRuntimeDependencies {
    $probeScript = @'
import importlib
import sys

modules = (
    "torch",
    "faster_whisper",
    "ctranslate2",
    "sounddevice",
    "soundfile",
    "transformers",
)
failures = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception as exc:
        failures.append(f"{name}: {type(exc).__name__}: {exc}")

if failures:
    sys.stderr.write("\n".join(failures) + "\n")
    raise SystemExit(1)
'@

    & uv run python -c $probeScript
    return ($LASTEXITCODE -eq 0)
}

function Repair-BridgeCalRuntimeDependencies {
    Write-Step "Attempting targeted runtime dependency reinstall..."
    & uv sync `
        --reinstall-package torch `
        --reinstall-package faster-whisper `
        --reinstall-package ctranslate2 `
        --reinstall-package sounddevice `
        --reinstall-package soundfile `
        --reinstall-package transformers
    return ($LASTEXITCODE -eq 0)
}

if (-not (Test-Path $RepoRoot)) {
    Fail "Repository root was not found: $RepoRoot"
}

Set-Location $RepoRoot

Write-Step "Checking Python..."
Ensure-Python

Write-Step "Checking uv..."
Ensure-Uv

if (-not $NoSync) {
    Write-Step "Installing dependencies with uv sync..."
    & uv sync
    if ($LASTEXITCODE -ne 0) {
        Fail "uv sync failed."
    }
}

Write-Step "Verifying runtime dependency imports..."
if (-not (Test-BridgeCalRuntimeDependencies)) {
    if ($NoSync) {
        Fail (
            "Runtime dependencies failed to import. Re-run without -NoSync, or run: " +
            "uv sync --reinstall-package torch --reinstall-package faster-whisper " +
            "--reinstall-package ctranslate2 --reinstall-package sounddevice " +
            "--reinstall-package soundfile --reinstall-package transformers"
        )
    }

    if (-not (Repair-BridgeCalRuntimeDependencies)) {
        Fail "Targeted dependency reinstall failed."
    }

    Write-Step "Re-checking runtime dependency imports..."
    if (-not (Test-BridgeCalRuntimeDependencies)) {
        Fail (
            "Runtime dependencies still failed to import. Install Microsoft Visual C++ " +
            "Redistributable (x64), then re-run this script."
        )
    }
}

$configArgs = @()
if (-not [string]::IsNullOrWhiteSpace($ConfigPath)) {
    $expandedConfigPath = [Environment]::ExpandEnvironmentVariables($ConfigPath)
    $configArgs += @("--config", $expandedConfigPath)
    if (-not (Test-Path $expandedConfigPath)) {
        Write-Step "Config file not found at $expandedConfigPath. GUI will open with this path."
    }
}

Write-Step "Launching BridgeCal GUI..."
& uv run bridgecal gui @configArgs
$guiExit = $LASTEXITCODE
if ($guiExit -ne 0) {
    Fail "BridgeCal GUI exited with code $guiExit." $guiExit
}

exit 0
