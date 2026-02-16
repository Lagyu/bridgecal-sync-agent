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

Actions:
- Delete the local token cache and re-run `bridgecal doctor` to re-authenticate.
- Confirm the OAuth consent screen and scopes include Calendar access.
- Confirm `google_client_secret.json` exists at the configured path in `config.toml`.

## Duplicate events / loops

Actions:
- Confirm mirror markers exist on both sides.
- Ensure the mapping DB is not being deleted between runs.
- Increase logging to debug and inspect mapping decisions.

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
