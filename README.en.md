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
uv run bridgecal availability --text "tomorrow 10:00-17:00"
uv run bridgecal gui
```

## Deploy On Windows

BridgeCal requires:
- Outlook desktop configured on the machine (COM access)
- Google OAuth client secret JSON for an OAuth **Desktop app**
- Python 3.12+
- The first availability check may take longer while the local LFM model is downloaded.

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

### Optional Windows GUI (manual sync + scheduler setup)

Launch:

```powershell
uv run bridgecal gui --config "$env:APPDATA\BridgeCal\config.toml"
```

Launch GUI with automatic dependency installation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-bridgecal-gui.ps1
```

Optional flags:

```powershell
.\scripts\run-bridgecal-gui.ps1 -ConfigPath "$env:APPDATA\BridgeCal\config.toml" -NoSync
```

The GUI can:
- run guided first-time setup (Google calendar ID + OAuth client secret)
- run one-time manual sync
- run doctor checks
- create/remove the logon scheduler task using admin elevation (UAC)
- run availability checks in a dedicated popup with voice/text input
  - selectable parser model: `LiquidAI/LFM2.5-1.2B-Thinking` / `Qwen/Qwen3-1.7B`
  - thinking mode is forced with max output tokens set to `16384`
  - stream `<think>...</think>` and final `<answer>...</answer>` into an in-popup LLM log box
- use Japanese UI by default and switch to English from the language selector

To use local LFM2.5 for availability parsing:
- parser backend is `transformers` + `torch`
- set `BRIDGECAL_LFM25_LOCAL_MODEL` (default: `LiquidAI/LFM2.5-1.2B-Instruct`)
- optionally set `BRIDGECAL_LFM25_LOCAL_DEVICE` (`cpu` / `auto`) and `BRIDGECAL_LFM25_LOCAL_TORCH_DTYPE`

Docs:
- `docs/index.md`
