# Architecture

## Overview

BridgeCal is a **local** sync agent that runs on the A-company Windows PC.

It bridges:
- Outlook calendar (read/write) via **Outlook COM automation**
- Google Calendar (read/write) via **Google Calendar API** (OAuth installed app flow)

No always-on server is required.

## High-level diagram (text)

    ┌───────────────────────────────────────────────┐
    │ A-company Windows PC                           │
    │                                               │
    │  ┌──────────────┐        ┌─────────────────┐  │
    │  │ Outlook Desktop│ COM   │ BridgeCal Agent │  │
    │  │ (Calendar)   │◄──────►│ (polling sync)  │  │
    │  └──────────────┘        └─────────┬───────┘  │
    └─────────────────────────────────────│──────────┘
                                          │ HTTPS (OAuth)
                                          ▼
                                 ┌──────────────────┐
                                 │ Google Calendar   │
                                 │ (B-company)       │
                                 └──────────────────┘

All other devices (B-company PCs, iPhone) use Google Calendar directly for the unified view.

The A-company PC can use either Outlook (with mirrored Google events) or Google Calendar web for the unified view.

## Components

### 1) OutlookClient
Responsibilities:
- Enumerate calendar items within the sync window.
- Read relevant fields (subject, start/end, location, body, all-day, last modified).
- Create/update/delete appointments.
- Store per-item sync metadata using `UserProperties`.

Implementation details:
- Uses `pywin32` (`win32com.client`) to talk to Outlook.
- Uses `Items.IncludeRecurrences = True` when scanning.

### 2) GoogleClient
Responsibilities:
- Enumerate events within the sync window.
- Use incremental sync via `syncToken` when available.
- Create/update/delete events.
- Store per-item sync metadata in `extendedProperties.private`.

Implementation details:
- Uses `google-api-python-client` with OAuth via `google-auth-oauthlib`.
- Uses `sendUpdates=none` to avoid email notifications.

### 3) MappingStore (SQLite)
Responsibilities:
- Maintain stable identity mapping between platforms:
  - Outlook EntryID (or GlobalAppointmentID where possible)
  - Google event ID
- Track last seen revision/hash to reduce churn.
- Store cursors/sync tokens.

### 4) SyncEngine
Responsibilities:
- Orchestrate two-way sync safely and deterministically.
- Loop prevention.
- Conflict resolution (last-write-wins).
- Produces structured stats and logs.

## Data flow per sync tick

1. Load config + open SQLite.
2. Fetch Outlook items in window.
3. Fetch Google events in window (incremental if possible).
4. Normalize both into a common `EventModel`.
5. Reconcile:
   - Create/update mirrors
   - Delete mirrors when source disappears
6. Persist mapping + cursors.
7. Emit summary logs and exit (or sleep and repeat).

## Key design decisions

- **Local-only**: avoids infra cost and respects Outlook API restrictions.
- **Idempotent markers**: prevents sync loops and makes operations safe to retry.
- **Rolling window**: bounded work per tick and predictable performance.

See also:
- `docs/sync.md` for algorithm and data model
- `docs/privacy-and-sharing.md` for confidentiality model
