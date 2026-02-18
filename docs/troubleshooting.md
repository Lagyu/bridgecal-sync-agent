# Troubleshooting

## Start here

Run:
- `uv run bridgecal doctor`

Doctor exit codes:
- `2`: config/prerequisite issue
- `3`: Google auth issue
- `4`: runtime/transient issue

## Outlook COM errors

Symptoms:
- “Class not registered”
- “Outlook is not responding”
- Permission prompts / security warnings

Actions:
- Ensure Outlook desktop is installed (not only “new Outlook” web wrapper).
- Start Outlook once interactively before running BridgeCal.
- Confirm the correct profile is configured.
- Verify BridgeCal is running on Windows (Outlook COM is Windows-only).

## Google auth errors

Symptoms:
- `invalid_grant`
- token refresh failures
- browser shows `Error 400: invalid_request` (for example, `gmail-chrome-extensions request is invalid`)

Actions:
- Delete the local token cache and re-run `bridgecal doctor` to re-authenticate.
- Confirm the OAuth consent screen and scopes include Calendar access.
- Confirm `google_client_secret.json` exists at the configured path in `config.toml`.
- Ensure the credential is an OAuth **Desktop app** JSON with an `installed` block that includes:
  - `client_id`
  - `client_secret`
  - `auth_uri`
  - `token_uri`
  - `redirect_uris` containing `http://localhost` (or `http://127.0.0.1`)
- Ensure `google_client_secret.json` is encoded as UTF-8 **without BOM**.
- If your network injects a corporate/self-signed certificate, install the corporate CA if
  possible. As a temporary workaround, set `google.insecure_tls_skip_verify = true` in
  `config.toml`.

## Duplicate events / loops

Actions:
- Confirm mirror markers exist on both sides.
- Ensure the mapping DB is not being deleted between runs.
- Increase logging to debug and inspect mapping decisions.
- BridgeCal intentionally skips Google events that are Outlook mirrors
  (`bridgecal.origin=outlook`). In sync output, compare `google_src` vs
  `google_mirror` to confirm how many are true Google-origin events.

Marker keys expected by BridgeCal:
- Google mirror events: `extendedProperties.private.bridgecal.origin=outlook`
- Google mirror events: `extendedProperties.private.bridgecal.outlook_id=<outlook_id>`
- Outlook mirrors: `UserProperties(\"BridgeCalOrigin\")=\"google\"`
- Outlook mirrors: `UserProperties(\"BridgeCalGoogleId\")=\"<google_id>\"`

## Timezone issues

Actions:
- Confirm Windows timezone is correct.
- Ensure Google calendar settings use the expected timezone.

## Command not found / import errors

Symptoms:
- `bridgecal: command not found`
- `ModuleNotFoundError: bridgecal`

Actions:
- Run via `uv run bridgecal ...` from the repo root.
- Ensure dependencies are installed with `uv sync`.

## Voice input DLL initialization failure (`WinError 1114`, `c10.dll`)

Symptoms:
- Voice input popup fails with an error similar to:
  `[WinError 1114] ... torch\\lib\\c10.dll`

Actions:
- Run the GUI launcher script instead of direct `uv run`:
  `powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\run-bridgecal-gui.ps1`
- The launcher now verifies runtime imports (`torch`, `faster_whisper`, etc.) and attempts targeted reinstall automatically.
- If it still fails, install Microsoft Visual C++ Redistributable (x64), then re-run the launcher.
