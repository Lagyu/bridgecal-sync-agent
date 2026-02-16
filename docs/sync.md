# Sync algorithm

## Canonical event model

BridgeCal normalizes Outlook appointments and Google events into a single internal model:

- `origin`: `outlook` or `google`
- `source_id`: stable id in origin system
- `start`, `end`: timezone-aware datetimes, or all-day date ranges
- `is_all_day`
- `summary`, `location`, `description`
- `busy_status`: Busy/Free (MVP uses Busy)
- `privacy`: Private/Public (MVP uses Private for mirrors)
- `last_modified`: datetime
- `fingerprint`: deterministic hash of relevant fields (for cheap change detection)

## Identity mapping

We maintain a mapping table:

- `outlook_id` (string)
- `google_event_id` (string)
- `origin` (who is authoritative for the pair)
- `last_outlook_modified`
- `last_google_updated`
- `last_outlook_fingerprint`
- `last_google_fingerprint`

Mirror markers:

- Google mirror event: `extendedProperties.private["bridgecal.origin"]="outlook"`
- Outlook mirror: `UserProperties("BridgeCalOrigin")="google"` and `UserProperties("BridgeCalGoogleId")="<id>"`

Any item with these markers is treated as a **mirror**, not a source.

## Reconciliation rules (MVP)

### Step 1 — classify
For each platform:
- Identify items in window.
- Partition into:
  - `sources` (no BridgeCal marker)
  - `mirrors` (has BridgeCal marker)

### Step 2 — build candidate pairs
Use mapping table first. If mapping is missing:
- Attempt a best-effort match using:
  - iCalUID (Google) vs Outlook GlobalAppointmentID (if available)
  - otherwise, (start,end,summary) heuristic with a narrow tolerance

New matches are written to the mapping table.

### Step 3 — compute actions
For each pair:
- If source exists and mirror missing: **create mirror**
- If both exist:
  - compute fingerprints and last_modified timestamps
  - apply conflict policy:
    - if source changed since last sync and mirror did not: update mirror
    - if both changed: last-write-wins
- If source missing and mirror exists: **delete mirror**

### Step 4 — execute with idempotency
All writes must be safe to retry:
- Creates include marker metadata.
- Updates are conditional where possible (Google uses etag; Outlook best-effort).
- Deletes ignore “not found”.

### Step 5 — persist cursors
- Save Google `syncToken` (if used).
- Save last Outlook scan time.

## Recurrence handling (MVP)

Outlook:
- Scan with `IncludeRecurrences=True`.
- Treat each instance within the window as a distinct logical item for mirroring.

Google:
- Use `singleEvents=True` when listing (expands recurring events into instances).
- Treat each instance as distinct for mirroring.

This is not perfect fidelity (exceptions, series edits), but is sufficient to avoid double-booking within the sync window.

## Safety rules

- Never copy attendees across systems.
- Never send email updates when creating/updating Google events (`sendUpdates=none`).
- Always set mirrors to Busy and Private by default.
