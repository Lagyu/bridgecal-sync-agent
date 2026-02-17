from __future__ import annotations

import base64
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TASK_NAME = "BridgeCal Sync Agent"


@dataclass(frozen=True)
class SchedulerOperationResult:
    ok: bool
    message: str
    exit_code: int = 0


def _ps_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def find_repo_root(start: Path | None = None) -> Path | None:
    probe = start or Path(__file__).resolve()
    if probe.is_file():
        probe = probe.parent

    for candidate in (probe, *probe.parents):
        if (candidate / "pyproject.toml").exists() and (
            candidate / "scripts" / "run-bridgecal-daemon.ps1"
        ).exists():
            return candidate
    return None


def find_runner_script(repo_root: Path | None = None) -> Path | None:
    root = repo_root or find_repo_root()
    if root is None:
        return None

    runner = root / "scripts" / "run-bridgecal-daemon.ps1"
    if not runner.exists():
        return None
    return runner


def build_register_task_script(
    *,
    runner_path: Path,
    config_path: Path,
    interval_seconds: int,
    task_name: str = TASK_NAME,
) -> str:
    runner_literal = _ps_single_quoted(str(runner_path))
    config_literal = _ps_single_quoted(str(config_path))
    task_literal = _ps_single_quoted(task_name)
    description_literal = _ps_single_quoted("BridgeCal Outlook<->Google sync daemon.")

    return f"""
$ErrorActionPreference = 'Stop'
$taskName = {task_literal}
$runnerPath = {runner_literal}
$configPath = {config_literal}
$intervalSeconds = {interval_seconds}

$psExe = (Get-Command powershell.exe).Source
$taskArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerPath`" -IntervalSeconds $intervalSeconds -ConfigPath `"$configPath`""
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction -Execute $psExe -Argument $taskArgs
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description {description_literal} -Force | Out-Null
Write-Output "Scheduled task configured: $taskName"
""".strip()


def build_remove_task_script(task_name: str = TASK_NAME) -> str:
    task_literal = _ps_single_quoted(task_name)
    return f"""
$ErrorActionPreference = 'Stop'
$taskName = {task_literal}
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $task) {{
    Write-Output "Scheduled task not found: $taskName"
    exit 0
}}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Output "Scheduled task removed: $taskName"
""".strip()


def _run_powershell(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def run_elevated_powershell(script: str) -> SchedulerOperationResult:
    if sys.platform != "win32":
        return SchedulerOperationResult(
            ok=False,
            message="Scheduler setup with admin elevation is only supported on Windows.",
            exit_code=1,
        )

    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    encoded_literal = _ps_single_quoted(encoded)
    launcher = (
        f"$encoded = {encoded_literal};"
        "$process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -PassThru -Wait "
        "-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded);"
        "if ($null -eq $process) { exit 1 };"
        "exit $process.ExitCode"
    )
    completed = _run_powershell(launcher)

    output = (completed.stdout or "").strip()
    errors = (completed.stderr or "").strip()
    if completed.returncode == 0:
        return SchedulerOperationResult(
            ok=True,
            message=output or "Operation completed successfully.",
            exit_code=0,
        )

    lowered = errors.lower()
    if "canceled by the user" in lowered or "cancelled by the user" in lowered:
        return SchedulerOperationResult(
            ok=False,
            message="Admin elevation was cancelled. Scheduler setup was not changed.",
            exit_code=completed.returncode,
        )

    detail = errors or output or "Unknown error while running elevated PowerShell."
    return SchedulerOperationResult(
        ok=False,
        message=detail,
        exit_code=completed.returncode,
    )


def configure_scheduler_with_elevation(
    *,
    config_path: Path,
    interval_seconds: int,
    task_name: str = TASK_NAME,
) -> SchedulerOperationResult:
    if interval_seconds <= 0:
        return SchedulerOperationResult(
            ok=False,
            message="Interval must be greater than zero.",
            exit_code=1,
        )

    runner_path = find_runner_script()
    if runner_path is None:
        return SchedulerOperationResult(
            ok=False,
            message="Unable to locate scripts/run-bridgecal-daemon.ps1 from this installation.",
            exit_code=1,
        )

    script = build_register_task_script(
        runner_path=runner_path,
        config_path=config_path,
        interval_seconds=interval_seconds,
        task_name=task_name,
    )
    return run_elevated_powershell(script)


def remove_scheduler_with_elevation(task_name: str = TASK_NAME) -> SchedulerOperationResult:
    script = build_remove_task_script(task_name=task_name)
    return run_elevated_powershell(script)


def query_scheduler_status(task_name: str = TASK_NAME) -> str:
    if sys.platform != "win32":
        return "Unsupported OS"

    task_literal = _ps_single_quoted(task_name)
    command = f"""
$task = Get-ScheduledTask -TaskName {task_literal} -ErrorAction SilentlyContinue
if ($null -eq $task) {{
    Write-Output "Not configured"
    exit 0
}}
$info = Get-ScheduledTaskInfo -TaskName {task_literal}
Write-Output ("Configured (" + $info.State + ")")
""".strip()
    completed = _run_powershell(command)
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()
        if detail:
            return f"Unknown ({detail})"
        return "Unknown"

    text = (completed.stdout or "").strip()
    return text or "Unknown"
