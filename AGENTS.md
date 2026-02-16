# BridgeCal Sync Agent — Agent Instructions (Repo Root)

This repository contains a **single-user** calendar sync agent that bridges:

- **A Company**: Microsoft Outlook (desktop client, Windows) — **no Microsoft cloud APIs** (Graph/EWS) allowed
- **B Company**: Google Calendar (Workspace / Google account)

Codex (and other coding agents) will read this file automatically before working. Keep it short and treat it as a **map**, not an encyclopedia.

## Source of truth

Start here:

- `docs/index.md` — documentation map
- `docs/requirements.md` — product requirements + acceptance criteria (what “done” means)
- `docs/architecture.md` — system design + data flow
- `docs/sync.md` — sync algorithm, idempotency, conflict rules

## Non‑negotiables (hard constraints)

- **No Microsoft Graph / EWS / Outlook REST**. Outlook access must be via the locally installed Outlook client on Windows (COM automation).
- **One user only** (the CEO). Do not build multi-tenant or multi-user abstractions.
- **No always-on server** required for synchronization. Sync runs only while the A-company Windows PC is on.
- **Never send cross-company invitations or email updates** when creating mirrored events.
- Preserve confidentiality:
  - When mirroring **A→Google**, set event visibility to *Private* and follow `docs/privacy-and-sharing.md`.
  - When mirroring **Google→Outlook**, set Outlook appointment sensitivity to *Private*.

## Repo conventions

### Language/tooling
- Python 3.12+.
- Package layout uses `src/` (importable as `bridgecal`).
- CLI is `bridgecal` (Typer).
- Local persistence: SQLite (mapping + sync cursors/tokens).

### Quality gates (run locally before considering work done)
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy .`
- `uv run pytest -q`

If you change behavior, update the relevant doc(s) in `docs/`.

### How to run (developer)
- Install deps: `uv sync`
- Run one sync pass: `uv run bridgecal sync --once`
- Run daemon: `uv run bridgecal sync --daemon --interval 120`

## Planning for complex changes (ExecPlans)

If you are about to implement a non-trivial feature (recurrences, conflict resolution changes, storage schema changes):
1. Create an ExecPlan in `docs/exec-plans/active/<short-name>.md` using the template in `docs/exec-plans/PLANS.md`.
2. Keep it updated as you implement.
3. Prefer small, reviewable commits.

## Security / privacy reminders

- OAuth tokens and local state live under `%APPDATA%\BridgeCal\` by default (configurable).
- Do not log event bodies/attendees unless explicitly enabled for debugging.
- Never commit real credentials, refresh tokens, or exported calendars.

## Where to put things

- `src/bridgecal/` — application code
- `src/bridgecal/sync/` — sync engine, models, mapping store
- `docs/` — human-readable design + runbooks
- `tests/` — unit tests (use fakes/mocks; keep tests deterministic)

