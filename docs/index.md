# BridgeCal Documentation Index

This repo implements **BridgeCal**, a single-user calendar sync agent bridging:

- Microsoft Outlook desktop calendar (A company, Windows only; no Graph/EWS allowed)
- Google Calendar (B company; API/CalDAV)

## Read this first

1. `requirements.md` — functional requirements + acceptance criteria
2. `architecture.md` — high-level architecture + components
3. `sync.md` — sync algorithm and data model
4. `privacy-and-sharing.md` — privacy model and recommended sharing settings

## Operate / run

- `setup.md` — local setup (Google OAuth, Outlook prerequisites)
- `runbook.md` — how to install and keep it running on the A-company PC
- `troubleshooting.md` — common failures and how to debug
- `security.md` — secrets handling, data minimization, logging

## Design logs

- `adr/` — architecture decision records
- `exec-plans/` — long-running planning docs (ExecPlans)
