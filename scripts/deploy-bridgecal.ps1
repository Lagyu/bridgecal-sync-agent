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

function Stop-RunningBridgeCal {
    param([string]$RepoRoot)

    $taskName = "BridgeCal Sync Agent"
    try {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
        if ($taskInfo.State -eq "Running") {
            Stop-ScheduledTask -TaskName $taskName
            Write-Step "Stopped running scheduled task '$taskName'."
        }
    } catch {
        # task missing or scheduler unavailable; continue
    }

    $bridgecalExePath = (Join-Path $RepoRoot ".venv\\Scripts\\bridgecal.exe").ToLowerInvariant()
    $repoRootLower = $RepoRoot.ToLowerInvariant()
    $targets = New-Object System.Collections.Generic.List[int]

    try {
        $processes = Get-CimInstance Win32_Process
    } catch {
        return
    }

    foreach ($process in $processes) {
        $exePath = [string]$process.ExecutablePath
        $commandLine = [string]$process.CommandLine
        $exeLower = if ([string]::IsNullOrWhiteSpace($exePath)) { "" } else { $exePath.ToLowerInvariant() }
        $cmdLower = if ([string]::IsNullOrWhiteSpace($commandLine)) { "" } else { $commandLine.ToLowerInvariant() }

        $isBridgecalExe = $exeLower -eq $bridgecalExePath
        $isRepoBridgecalCmd = (
            -not [string]::IsNullOrWhiteSpace($cmdLower) -and
            $cmdLower.Contains($repoRootLower) -and
            ($cmdLower.Contains("bridgecal") -or $cmdLower.Contains("run-bridgecal-daemon"))
        )

        if ($isBridgecalExe -or $isRepoBridgecalCmd) {
            $pidValue = [int]$process.ProcessId
            if ($pidValue -ne $PID -and -not $targets.Contains($pidValue)) {
                $targets.Add($pidValue)
            }
        }
    }

    if ($targets.Count -eq 0) {
        return
    }

    foreach ($pidValue in $targets) {
        try {
            Stop-Process -Id $pidValue -Force -ErrorAction Stop
        } catch {
            # already exited or inaccessible; continue
        }
    }
    Write-Step "Stopped $($targets.Count) running BridgeCal process(es)."
}

function Write-Utf8NoBomFile {
    param(
        [string]$Path,
        [string]$Content
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Read-Utf8NoBomText {
    param(
        [string]$Path,
        [string]$FriendlyName
    )

    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
    } catch {
        Fail "Unable to read $FriendlyName at $Path"
    }

    $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
    if ($hasBom) {
        Write-Step "$FriendlyName has UTF-8 BOM. Converting to UTF-8 without BOM."
        if ($bytes.Length -eq 3) {
            return ""
        }
        $bytes = $bytes[3..($bytes.Length - 1)]
    }

    $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    try {
        return $strictUtf8.GetString($bytes)
    } catch {
        Fail "$FriendlyName must be UTF-8 text: $Path"
    }
}

function Normalize-Utf8NoBomFile {
    param(
        [string]$Path,
        [string]$FriendlyName = "File"
    )

    if (-not (Test-Path $Path)) {
        return
    }

    $text = Read-Utf8NoBomText -Path $Path -FriendlyName $FriendlyName
    Write-Utf8NoBomFile -Path $Path -Content $text
}

function Normalize-JsonFileUtf8NoBom {
    param(
        [string]$Path,
        [string]$FriendlyName
    )

    $text = Read-Utf8NoBomText -Path $Path -FriendlyName $FriendlyName

    try {
        $null = $text | ConvertFrom-Json
    } catch {
        Fail "$FriendlyName is not valid JSON: $Path"
    }

    Write-Utf8NoBomFile -Path $Path -Content $text
}

function Validate-DesktopClientSecretJsonObject {
    param(
        [object]$Json,
        [string]$FriendlyName
    )

    if (-not ($Json.PSObject.Properties.Name -contains "installed")) {
        Fail "$FriendlyName must contain an 'installed' object. Create OAuth Client ID type 'Desktop app' in Google Cloud and download the JSON."
    }

    $installed = $Json.installed
    $requiredFields = @("client_id", "client_secret", "auth_uri", "token_uri", "redirect_uris")
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($field in $requiredFields) {
        if (-not ($installed.PSObject.Properties.Name -contains $field)) {
            $missing.Add($field)
            continue
        }

        $value = $installed.$field
        if ($null -eq $value) {
            $missing.Add($field)
            continue
        }

        if ($field -ne "redirect_uris" -and [string]::IsNullOrWhiteSpace([string]$value)) {
            $missing.Add($field)
            continue
        }

        if ($field -eq "redirect_uris" -and @($value).Count -eq 0) {
            $missing.Add($field)
            continue
        }
    }

    if ($missing.Count -gt 0) {
        $names = [string]::Join(", ", $missing)
        Fail "$FriendlyName is missing required fields: $names"
    }

    $redirectUris = @($installed.redirect_uris)
    $hasLocalRedirect = $false
    foreach ($uri in $redirectUris) {
        if ($uri -is [string] -and ($uri.StartsWith("http://localhost") -or $uri.StartsWith("http://127.0.0.1"))) {
            $hasLocalRedirect = $true
            break
        }
    }
    if (-not $hasLocalRedirect) {
        Fail "$FriendlyName is not a valid Desktop app OAuth credential. redirect_uris must include localhost/127.0.0.1."
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
insecure_tls_skip_verify = true

[sync]
interval_seconds = $SyncIntervalSeconds
redaction_mode = "none"
"@

    Write-Utf8NoBomFile -Path $ConfigPath -Content $content
}

function Save-ClientSecretJson {
    param(
        [string]$DestinationPath
    )

    if (Test-Path $DestinationPath) {
        $overwrite = Confirm-YesNo -Prompt "google_client_secret.json already exists. Overwrite?" -Default $false
        if (-not $overwrite) {
            Normalize-JsonFileUtf8NoBom -Path $DestinationPath -FriendlyName "Existing google_client_secret.json"
            $existingText = Read-Utf8NoBomText -Path $DestinationPath -FriendlyName "Existing google_client_secret.json"
            $existingJson = $existingText | ConvertFrom-Json
            Validate-DesktopClientSecretJsonObject -Json $existingJson -FriendlyName "Existing google_client_secret.json"
            Write-Step "Keeping existing client secret file."
            return
        }
    }

    Write-Host ""
    Write-Host "Google OAuth client secret (Desktop app) is required."
    $sourcePath = Read-Host "Enter path to client secret JSON (or press Enter to paste JSON)"

    $jsonText = ""
    if (-not [string]::IsNullOrWhiteSpace($sourcePath)) {
        $resolved = (Resolve-Path $sourcePath -ErrorAction Stop).Path
        $jsonText = Read-Utf8NoBomText -Path $resolved -FriendlyName "Source client secret JSON"
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
    $jsonText = $jsonText.TrimStart([char]0xFEFF)

    try {
        $json = $jsonText | ConvertFrom-Json
    } catch {
        Fail "The provided client secret is not valid JSON. $($_.Exception.Message)"
    }

    Validate-DesktopClientSecretJsonObject -Json $json -FriendlyName "google_client_secret.json"

    Write-Utf8NoBomFile -Path $DestinationPath -Content $jsonText
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
Stop-RunningBridgeCal -RepoRoot $RepoRoot

$syncSucceeded = $false
for ($attempt = 1; $attempt -le 2; $attempt++) {
    & uv sync
    if ($LASTEXITCODE -eq 0) {
        $syncSucceeded = $true
        break
    }

    if ($attempt -eq 1) {
        Write-Warning "uv sync failed (attempt 1). Retrying after stopping BridgeCal processes."
        Stop-RunningBridgeCal -RepoRoot $RepoRoot
    }
}

if (-not $syncSucceeded) {
    Pop-Location
    Fail "uv sync failed."
}

Write-Step "Verifying runtime dependency imports..."
if (-not (Test-BridgeCalRuntimeDependencies)) {
    if (-not (Repair-BridgeCalRuntimeDependencies)) {
        Pop-Location
        Fail "Targeted dependency reinstall failed."
    }

    Write-Step "Re-checking runtime dependency imports..."
    if (-not (Test-BridgeCalRuntimeDependencies)) {
        Pop-Location
        Fail (
            "Runtime dependencies still failed to import. Install Microsoft Visual C++ " +
            "Redistributable (x64), then re-run this script."
        )
    }
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
        Normalize-Utf8NoBomFile -Path $configPath -FriendlyName "Existing config.toml"
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
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
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
