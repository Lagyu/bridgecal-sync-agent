# Runbook (Operations)

## Recommended deployment model

BridgeCal is a local agent. Recommended options:

### Option A — Windows Task Scheduler (simplest)
- Trigger: at logon
- Action: `uv run bridgecal sync --daemon --interval 120`
- Run whether user is logged on or not (optional, depends on policy)

### Option B — Startup shortcut (lightweight)
- Put a shortcut in `shell:startup` to run BridgeCal in daemon mode.

## Pre-flight checks

Run before first launch and after any config/auth changes:

- `uv run bridgecal doctor`

Doctor exit codes:
- `0`: all checks passed
- `2`: configuration/prerequisite issue
- `3`: Google authentication issue
- `4`: runtime/transient issue

## Upgrades

1. Pull latest code.
2. `uv sync --extra dev` (or `uv sync` for runtime-only machines)
3. Restart the scheduled task / process.

## Manual operations

- One sync pass: `uv run bridgecal sync --once`
- Daemon mode: `uv run bridgecal sync --daemon --interval 120`
- Debug logging: add `--debug` to either command

## Backups

Copy `%APPDATA%\\BridgeCal\\state.db` if you need to preserve mappings and cursors.
If moving machines, copy these together:
- `%APPDATA%\\BridgeCal\\config.toml`
- `%APPDATA%\\BridgeCal\\google_token.json`
- `%APPDATA%\\BridgeCal\\state.db`

## Observability

- Logs: `%APPDATA%\\BridgeCal\\bridgecal.log`
- Use `uv run bridgecal doctor` to validate environment quickly.
- Sync command prints per-pass counters: scanned/create/update/delete for both platforms.
