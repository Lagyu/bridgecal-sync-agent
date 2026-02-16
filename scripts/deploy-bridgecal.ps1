param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$DataDir = (Join-Path $env:APPDATA "BridgeCal"),
    [int]$IntervalSeconds = 120,
    [switch]$SkipScheduledTask
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[BridgeCal] $Message" -ForegroundColor Cyan
}

function Fail {
    param(
        [string]$Message,
        [int]$ExitCode = 1
    )
    Write-Error $Message
    exit $ExitCode
}

function Confirm-YesNo {
    param(
        [string]$Prompt,
        [bool]$Default = $true
    )

    $hint = if ($Default) { "Y/n" } else { "y/N" }
    $response = Read-Host "$Prompt [$hint]"
    if ([string]::IsNullOrWhiteSpace($response)) {
        return $Default
    }

    switch ($response.Trim().ToLowerInvariant()) {
        "y" { return $true }
        "yes" { return $true }
        "n" { return $false }
        "no" { return $false }
        default { return $Default }
    }
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
        [string]$FriendlyName
    )

    Write-Step "Installing $FriendlyName via winget ($PackageId)..."
    & winget install --id $PackageId -e --scope user --accept-source-agreements --accept-package-agreements
    return ($LASTEXITCODE -eq 0)
}

function Test-Python312 {
    try {
        & py -3.12 -c "import sys" | Out-Null
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

function Write-ConfigFile {
    param(
        [string]$ConfigPath,
        [string]$TomlDataDir,
        [string]$CalendarId,
        [int]$SyncIntervalSeconds
    )

    $content = @"
data_dir = "$TomlDataDir"

[outlook]
past_days = 30
future_days = 180

[google]
calendar_id = "$CalendarId"
client_secret_path = "google_client_secret.json"
token_path = "google_token.json"

[sync]
interval_seconds = $SyncIntervalSeconds
redaction_mode = "none"
"@

    Set-Content -Path $ConfigPath -Encoding utf8 -Value $content
}

function Save-ClientSecretJson {
    param(
        [string]$DestinationPath
    )

    if (Test-Path $DestinationPath) {
        $overwrite = Confirm-YesNo -Prompt "google_client_secret.json already exists. Overwrite?" -Default $false
        if (-not $overwrite) {
            Write-Step "Keeping existing client secret file."
            return
        }
    }

    Write-Host ""
    Write-Host "Google OAuth client secret (Desktop app) is required."
    $sourcePath = Read-Host "Enter path to client secret JSON (or press Enter to paste JSON)"

    $jsonText = ""
    if (-not [string]::IsNullOrWhiteSpace($sourcePath)) {
        $resolved = Resolve-Path $sourcePath -ErrorAction Stop
        $jsonText = Get-Content -Path $resolved -Raw
    } else {
        Write-Host "Paste JSON now. Type ENDJSON on a new line when done."
        $lines = New-Object System.Collections.Generic.List[string]
        while ($true) {
            $line = Read-Host
            if ($line -eq "ENDJSON") {
                break
            }
            $lines.Add($line)
        }
        $jsonText = ($lines -join [Environment]::NewLine).Trim()
    }

    if ([string]::IsNullOrWhiteSpace($jsonText)) {
        Fail "Client secret JSON was empty."
    }

    try {
        $json = $jsonText | ConvertFrom-Json
        if (-not ($json.PSObject.Properties.Name -contains "installed")) {
            Write-Warning "The JSON does not contain an 'installed' block. Ensure this is a Desktop app OAuth credential."
        }
    } catch {
        Fail "The provided client secret is not valid JSON."
    }

    Set-Content -Path $DestinationPath -Encoding utf8 -Value $jsonText
    Write-Step "Saved Google client secret to $DestinationPath"
}

$isWindowsHost = $env:OS -eq "Windows_NT"
if (-not $isWindowsHost) {
    Fail "This deployment script must run on Windows."
}

if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
    Fail "Repo root appears invalid: $RepoRoot (pyproject.toml not found)."
}

if ($IntervalSeconds -le 0) {
    Fail "IntervalSeconds must be greater than 0."
}

Write-Step "Checking Python..."
Ensure-Python

Write-Step "Checking uv..."
Ensure-Uv

Write-Step "Installing dependencies with uv sync..."
Push-Location $RepoRoot
& uv sync
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Fail "uv sync failed."
}
Pop-Location

Write-Step "Preparing data directory: $DataDir"
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null

$configPath = Join-Path $DataDir "config.toml"
$calendarId = "primary"
if (Test-Path $configPath) {
    $keep = Confirm-YesNo -Prompt "config.toml already exists. Keep existing config?" -Default $true
    if (-not $keep) {
        $inputCalendarId = Read-Host "Google calendar ID to sync (default: primary)"
        if (-not [string]::IsNullOrWhiteSpace($inputCalendarId)) {
            $calendarId = $inputCalendarId.Trim()
        }
        $tomlDataDir = $DataDir -replace "\\", "/"
        Write-ConfigFile -ConfigPath $configPath -TomlDataDir $tomlDataDir -CalendarId $calendarId -SyncIntervalSeconds $IntervalSeconds
        Write-Step "Wrote config to $configPath"
    } else {
        Write-Step "Keeping existing config: $configPath"
    }
} else {
    $inputCalendarId = Read-Host "Google calendar ID to sync (default: primary)"
    if (-not [string]::IsNullOrWhiteSpace($inputCalendarId)) {
        $calendarId = $inputCalendarId.Trim()
    }
    $tomlDataDir = $DataDir -replace "\\", "/"
    Write-ConfigFile -ConfigPath $configPath -TomlDataDir $tomlDataDir -CalendarId $calendarId -SyncIntervalSeconds $IntervalSeconds
    Write-Step "Wrote config to $configPath"
}

$clientSecretPath = Join-Path $DataDir "google_client_secret.json"
Save-ClientSecretJson -DestinationPath $clientSecretPath

Write-Step "Running doctor check (this may open a browser for Google OAuth)..."
Push-Location $RepoRoot
& uv run bridgecal doctor --config $configPath
$doctorExit = $LASTEXITCODE
Pop-Location
if ($doctorExit -ne 0) {
    Fail "bridgecal doctor failed with exit code $doctorExit." $doctorExit
}

$runInitialSync = Confirm-YesNo -Prompt "Run an initial one-time sync now?" -Default $true
if ($runInitialSync) {
    Write-Step "Running initial sync pass..."
    Push-Location $RepoRoot
    & uv run bridgecal sync --once --config $configPath
    $syncExit = $LASTEXITCODE
    Pop-Location
    if ($syncExit -ne 0) {
        Write-Warning "Initial sync returned exit code $syncExit. Check bridgecal.log for details."
    }
}

if (-not $SkipScheduledTask) {
    $createTask = Confirm-YesNo -Prompt "Create/update scheduled task to run BridgeCal at logon?" -Default $true
    if ($createTask) {
        $taskName = "BridgeCal Sync Agent"
        $runnerPath = (Resolve-Path (Join-Path $RepoRoot "scripts\\run-bridgecal-daemon.ps1")).Path
        $psExe = (Get-Command powershell.exe).Source
        $taskArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerPath`" -IntervalSeconds $IntervalSeconds -ConfigPath `"$configPath`""
        $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

        $action = New-ScheduledTaskAction -Execute $psExe -Argument $taskArgs
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel LeastPrivilege
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "BridgeCal Outlook<->Google sync daemon." -Force | Out-Null
        Write-Step "Scheduled task '$taskName' is configured."
    }
}

Write-Host ""
Write-Host "Deployment complete."
Write-Host "Config: $configPath"
Write-Host "Data dir: $DataDir"
Write-Host "Log: $(Join-Path $DataDir "bridgecal.log")"
