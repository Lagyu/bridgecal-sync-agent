# BridgeCal Sync Agent

[日本語版 README](README.ja.md)

BridgeCal is a **single-user**, **local** sync agent that keeps two calendars aligned:

- Microsoft Outlook desktop calendar (A company, Windows; no Graph/EWS allowed)
- Google Calendar (B company)

The agent runs only while the A-company PC is on.

## Quickstart (dev)

```bash
uv sync
uv run bridgecal doctor
uv run bridgecal sync --once
```

## Deploy On Windows

BridgeCal requires:
- Outlook desktop configured on the machine (COM access)
- Google OAuth client secret JSON for an OAuth **Desktop app**
- Python 3.12+

No Google API key is required.

### One-command deploy (PowerShell)

Run from repo root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-bridgecal.ps1
```

What the script does:
- installs Python 3.12+ via `winget` if missing
- installs `uv` via `winget` if missing (falls back to official installer)
- runs `uv sync`
- creates `%APPDATA%\BridgeCal\config.toml`
- prompts for Google calendar ID
- prompts for Google OAuth client secret (file path or pasted JSON)
- runs `uv run bridgecal doctor`
- optionally runs initial `uv run bridgecal sync --once`
- optionally creates a startup scheduled task

Note: Outlook is not installed by this script; Outlook desktop must already be installed and configured.

Optional flags:

```powershell
.\scripts\deploy-bridgecal.ps1 -IntervalSeconds 120 -SkipScheduledTask
```

### Daemon runner script

If needed directly (for Task Scheduler action):

```powershell
.\scripts\run-bridgecal-daemon.ps1 -IntervalSeconds 120 -ConfigPath "$env:APPDATA\BridgeCal\config.toml"
```

Docs:
- `docs/index.md`
