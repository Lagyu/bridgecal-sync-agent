# Setup

This project is intended to run on the **A-company Windows PC**.

## Prerequisites

- Windows 10/11
- Outlook desktop installed and configured (Microsoft 365 Apps / Office)
- Python 3.12+
- Network access to Google Calendar endpoints from the A-company PC

## Google OAuth (installed app)

1. Create (or obtain) a Google Cloud project in the B-company environment.
2. Enable the Google Calendar API.
3. Create OAuth credentials of type “Desktop app”.
4. Download the client secret JSON and save it as:
   - `%APPDATA%\BridgeCal\google_client_secret.json`

BridgeCal will open a browser for the initial OAuth consent and store a refresh token locally.

## Configure BridgeCal

Copy the example config:

- `config/config.example.toml` → `%APPDATA%\BridgeCal\config.toml`

Then edit:
- the Google calendar id
- sync window
- polling interval
- `google.insecure_tls_skip_verify` (`true` ignores TLS cert validation for Google API calls)

## First run

Run:
- `uv run bridgecal doctor`
- `uv run bridgecal sync --once`

Optional GUI (Windows):
- `uv run bridgecal gui --config "%APPDATA%\\BridgeCal\\config.toml"`
- supports manual sync, doctor, and elevated scheduler setup/removal
- includes a first-time setup assistant for calendar ID + client secret
- includes an availability popup (voice/text input) for checking free/busy time ranges
- auto-bootstrap launcher: `powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\run-bridgecal-gui.ps1`

If successful, it will create:
- `%APPDATA%\BridgeCal\state.db`
- `%APPDATA%\BridgeCal\bridgecal.log`
