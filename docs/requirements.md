# Requirements

## Context

We have a single user (the CEO) who participates in two separate organizations:

- **A Company** uses Microsoft Outlook / Exchange. Microsoft cloud APIs are not available due to IT restrictions.
- **B Company** uses Google Calendar.

The CEO uses:
- A-company Windows PC (Outlook is installed and configured)
- B-company PCs (Windows + macOS)
- Personal iPhone

The CEO wants a unified schedule and bidirectional synchronization between the two calendars, while preventing cross-company information leakage.

## Goals

### G1 — Unified calendar view on all devices
The CEO must be able to see a combined schedule from:
- A-company Windows PC
- B-company Windows/macOS PCs
- iPhone

### G2 — Bidirectional sync (create/update/delete)
When an event is created, updated, or deleted on either side, the corresponding mirrored event is created/updated/deleted on the other side.

### G3 — Runs only when A-company PC is on
The sync system does **not** require always-on servers. If the A-company PC is off, sync can lag; it should catch up when the PC is next on.

### G4 — Privacy / confidentiality
The CEO can see full details on each system, but other users must not see the other company’s details.

Operationally this is implemented via:
- **Google events mirrored from Outlook** are set to `visibility=private`.
- **Outlook appointments mirrored from Google** are set to `Sensitivity=olPrivate`.

See `privacy-and-sharing.md` for the sharing settings required for this to work.

## Phased delivery (pragmatic for a ~3-day build)

### MVP (Phase 1)
- Bidirectional sync (create/update/delete) within a rolling window.
- Unified viewing primarily via **Google Calendar** (because it is available on all devices).
- Private mirrors on both platforms.
- CLI + local persistence + logs.

### Voice / speech (Phase 1.5)
To keep cost and complexity low, the first approach is to **reuse device-native voice dictation/assistants**:
- iPhone/macOS: add the B-company Google account to Apple Calendar; use Siri to query/add events.
- Windows: use OS dictation into the Google Calendar web UI or Outlook (manual).

If this is insufficient, implement Phase 2.

### Phase 2 (optional)
A small “command console” web app that accepts speech → text and executes:
- “What’s on my calendar between <time range>?”
- “Add <event>”

This can run as a low-cost serverless API (AWS API Gateway + Lambda) targeting Google Calendar only (since Outlook sync is handled by the local agent).


## Non-goals (explicitly out of scope for MVP)

- Multi-user support.
- Real-time push sync while the A-company PC is off.
- Perfect fidelity for every Outlook/Google feature (attachments, complex resources, advanced conferencing).
- Cross-company attendee synchronization (do not invite attendees across companies).

## Constraints

- Outlook access must be via **Outlook desktop COM automation on Windows**.
- Google Calendar API might be available; if not, a CalDAV fallback may be implemented later.
- Only one user exists; simplifications are allowed accordingly.
- Data and tokens must be stored locally on the A-company PC.

## Assumptions

- Reconciliation is mapping-first for MVP. Existing unrelated events that look similar across both systems are not auto-matched by heuristics during initial bootstrap.
- Recurring events are synchronized as expanded instances inside the configured window (no full-series semantic merge in MVP).

## Terminology

- **Source event**: an event originally created in its native calendar (Outlook or Google).
- **Mirror event**: an event created by BridgeCal to represent a source event in the other calendar.
- **Origin**: where the source event lives (`outlook` or `google`).

## Functional requirements

### FR1 — Sync window
BridgeCal synchronizes events within a rolling time window:

- Past window: configurable (default 30 days)
- Future window: configurable (default 180 days)

All-day events are included.

### FR2 — A → B (Outlook → Google)
For each Outlook event in the sync window that is not a mirror:
- Create or update the corresponding Google event.
- Set Google event fields:
  - Summary/title: mirrored from Outlook (MVP supports copying full title)
  - Start/end dateTime or date (all-day)
  - Location, description/notes (copy in MVP; can be redacted by config)
  - Visibility: `private`
  - Transparency: `opaque` (blocks time)
- Do **not** add attendees or send updates (`sendUpdates=none`).

### FR3 — B → A (Google → Outlook)
For each Google event in the sync window that is not a mirror:
- Create or update the corresponding Outlook appointment.
- Set Outlook appointment fields:
  - Subject, start, end, location, body/notes (copy in MVP; can be redacted by config)
  - Sensitivity: `olPrivate`
  - BusyStatus: Busy (block time)
- Do **not** create a meeting request or send invitations.

### FR4 — Deletes/cancellations
If a source event is deleted or cancelled:
- The mirror event must be deleted on the other side.

### FR5 — Loop prevention & idempotency
BridgeCal must not endlessly re-sync its own mirror events.

Approach:
- Google mirror events contain a `extendedProperties.private` marker with origin metadata.
- Outlook mirror appointments contain a `UserProperty` marker with origin metadata.

### FR6 — Conflict handling
If both sides change “the same” event before the next sync, the system must apply a deterministic rule.

MVP policy:
- **Last-write-wins** using each platform’s last-modified timestamp.
- If timestamps are missing/ambiguous, prefer Outlook as authoritative.

All conflict decisions must be logged.

### FR7 — Local persistence
BridgeCal maintains local state under a configurable data directory (default: `%APPDATA%\BridgeCal\`):

- `state.db` (SQLite):
  - mapping table: outlook_id ⇄ google_event_id
  - per-item hashes / last seen revision for cheap change detection
  - google `syncToken` (if using incremental sync)
  - last successful Outlook scan cursor/time
- structured logs: `bridgecal.log` (rotating)
- config file: `config.toml` (user-managed)

### FR8 — CLI
Provide a CLI with subcommands:

- `bridgecal doctor` — validates prerequisites (Outlook availability, Google auth, permissions, config)
- `bridgecal sync --once` — runs one sync pass
- `bridgecal sync --daemon --interval <seconds>` — runs in a loop

Exit codes must be meaningful:
- `0`: success
- `2`: configuration error
- `3`: authentication error
- `4`: runtime error (transient)

### FR9 — Observability
- Log high-level stats per sync pass: scanned counts, created/updated/deleted counts.
- Avoid logging sensitive event content by default.
- Provide a `--debug` flag to increase verbosity.


### FR10 — Voice interactions (phased)
BridgeCal itself is a sync agent and does not need to implement speech recognition in MVP.

However, the overall solution must enable voice-based:
- schedule checks for a time range
- event creation

Phase 1.5 uses device-native assistants/dictation; Phase 2 adds a dedicated web “command console”.

See `docs/voice-ui.md`.

## Acceptance criteria (MVP)

A1. Creating an event in Outlook results in a mirrored event in Google after running `bridgecal sync --once`.

A2. Updating time/title/location in Outlook updates the mirror in Google.

A3. Deleting an Outlook event deletes its mirror in Google.

A4. The same holds in the opposite direction (Google → Outlook).

A5. Mirror events are marked private on both platforms (Google `visibility=private`, Outlook `Sensitivity=olPrivate`).

A6. Running `bridgecal sync --once` twice in a row without changes produces **no net changes** on either calendar.

A7. `bridgecal doctor` reports actionable errors when prerequisites are missing.
