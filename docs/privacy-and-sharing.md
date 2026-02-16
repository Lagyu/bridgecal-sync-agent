# Privacy and sharing model

## What we must protect

- A-company events must not leak details to B-company users.
- B-company events must not leak details to A-company users.

BridgeCal enforces “private” on mirrored items, but **calendar sharing permissions still matter**.

## Google Calendar: event visibility vs calendar permissions

BridgeCal creates mirrored A-company events in Google Calendar with:
- `visibility = "private"`
- `transparency = "opaque"` (blocks time)

Important implication:
- Users who have **"See all event details"** permission on the calendar will still *not* see details for events marked *Private*.
- Users who have **edit permissions** ("Make changes to events" / "Make changes & manage sharing") can see private event details.

Therefore, if you must hide A-company details from a B-company assistant:
- Prefer **not** granting edit permission to your calendar.
- Use invitations / appointment schedules / booking workflows instead of giving edit access.

## Outlook: private appointments

BridgeCal creates mirrored B-company items in Outlook with:
- `AppointmentItem.Sensitivity = olPrivate`
- Busy status set to Busy

Delegates typically see private items as “Private Appointment” without details, depending on mailbox policy.

## Data handling in BridgeCal

- BridgeCal stores sync state locally (SQLite) and does not upload it anywhere.
- Logs are redacted by default (do not include descriptions).
- A debug flag can opt into more verbose logging; treat debug logs as sensitive.

## Optional: redaction mode (future / configurable)

If policy requires stronger protection (e.g. editors must not see details):
- Mirror with redacted summary/body (e.g. “Busy”) instead of full details.
- Or mirror full details into a private calendar visible only to the CEO, plus a redacted Busy block calendar shared to others.

This is not implemented in MVP by default, but the config should be designed to allow it.
