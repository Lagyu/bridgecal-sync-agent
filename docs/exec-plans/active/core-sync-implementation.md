# ExecPlan: Core Sync Implementation

## Goal
Implement the BridgeCal MVP behavior end-to-end: Outlook COM client, Google Calendar API client, sync reconciliation, CLI wiring, deterministic tests, and operator docs.

## Non-goals
- Multi-user abstractions.
- Always-on background services outside local daemon mode.
- Full recurrence fidelity beyond expanded instances inside the configured window.
- Automatic attendee synchronization.

## Current behavior
- `src/bridgecal/outlook_client.py` is a scaffold.
- `src/bridgecal/google_client.py` is a scaffold.
- `src/bridgecal/sync/engine.py` only scans and returns counts.
- `src/bridgecal/commands/doctor.py` and `src/bridgecal/commands/sync.py` are not wired to real checks/engine.
- `tests/test_engine.py` only verifies scaffold execution.

## Proposed behavior
- Outlook and Google clients expose concrete `list_events`, `upsert_mirror`, and `delete_event` operations with privacy-preserving mirror markers.
- Sync engine performs deterministic two-way reconciliation with loop prevention, mapping-store persistence, last-write-wins conflict handling, and delete propagation.
- CLI commands run real checks and sync passes with summary counts and meaningful error codes.
- Unit tests cover loop prevention, create/update/delete, and idempotency.

## Design
- Data model changes:
  - Extend canonical events with mirror metadata so the engine can explicitly classify source vs mirror items.
  - Extend mapping rows with `origin` and provide methods to list and delete mappings by id.
- Algorithm changes:
  - Partition scanned events into source/mirror sets.
  - Reconcile using mapping-first logic in both directions.
  - Detect deletion using missing source in mapped pairs.
  - Resolve conflicts with timestamp comparisons; tie/unknown defaults to Outlook.
- Edge cases:
  - Outlook COM unavailable on non-Windows host.
  - Missing/expired Google token requiring refresh/login.
  - Mirror target not found on delete/update (ignore and continue).

## Implementation steps (checklist)
- [x] Implement canonical model helpers and mapping-store schema/helpers.
- [x] Implement Outlook COM client with marker handling and privacy defaults.
- [x] Implement Google Calendar client with OAuth flow, marker handling, and `sendUpdates=none`.
- [x] Implement sync engine reconciliation and summary stats updates.
- [x] Wire CLI doctor/sync commands to concrete components and error handling.
- [x] Expand deterministic unit tests and run quality gates.
- [x] Update runbook/troubleshooting and assumptions documentation.

## Testing plan
- Unit tests:
  - Loop prevention.
  - Create/update/delete in both directions.
  - Two-pass idempotency with unchanged inputs.
- Integration tests:
  - Optional only; skipped by default.
- Manual test script:
  - `uv run bridgecal doctor`
  - `uv run bridgecal sync --once`
  - `uv run bridgecal sync --daemon --interval 120`

## Rollout / operations
- Backward compatibility:
  - Mapping schema initialized/migrated automatically on startup.
- Revert:
  - Restore previous package revision and remove generated local state for clean re-bootstrap.

## Decision log
- 2026-02-16: Keep reconciliation strictly mapping-driven for deterministic behavior in MVP; skip heuristic matching for unmapped pre-existing items to avoid false-positive joins.
- 2026-02-16: Use marker-aware source filtering in the engine to enforce loop prevention, and keep mirror writes idempotent through stable source↔mirror mapping rows.
