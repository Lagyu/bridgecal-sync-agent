# Security

## Secrets

- Google OAuth refresh tokens are stored locally.
- Never commit:
  - OAuth client secrets
  - refresh tokens
  - exported calendars
  - logs containing sensitive content

## Local data at rest

Default data directory: `%APPDATA%\BridgeCal\`

Contains:
- `config.toml`
- `state.db` (SQLite)
- OAuth token cache (implementation-defined)

Recommended:
- Restrict file permissions to the user account.
- Treat the directory as sensitive.

## Logging

By default, logs must:
- Include IDs, counts, timestamps, errors.
- Exclude event body and attendees.
- Optionally include event summaries for debugging behind `--debug`.

## Network

Only Google Calendar API endpoints are required. No inbound ports.
