# ADR 0001: Local sync agent on the A-company PC

## Status
Accepted

## Context
- Outlook cloud APIs are unavailable due to A-company IT policy.
- The CEO needs bidirectional sync with Google Calendar, but only while the A-company PC is on.
- We want minimal infra cost and operational overhead.

## Decision
Implement BridgeCal as a local polling agent running on the A-company Windows PC, using:
- Outlook desktop COM automation for Outlook read/write
- Google Calendar API (OAuth) for Google read/write
- Local SQLite for mapping and cursors

## Consequences
Pros:
- No server to maintain.
- Works without Microsoft cloud APIs.
- Simple operational model.

Cons:
- Sync only happens when the PC is on.
- Outlook COM automation is Windows-only and can be brittle; requires careful error handling.
