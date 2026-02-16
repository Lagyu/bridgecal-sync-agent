# ADR 0002: Loop prevention via per-item markers

## Status
Accepted

## Context
Bidirectional sync can create infinite loops if the agent re-syncs the mirror items it creates.

## Decision
Mark mirror items:
- Google: `extendedProperties.private["bridgecal.origin"] = "outlook"` or `"google"`
- Outlook: `UserProperties("BridgeCalOrigin") = ...` plus id fields

The sync engine must treat any marked item as a mirror and never mirror it again.

## Consequences
- Idempotent behavior; safe retries.
- Requires care to ensure markers persist and are reliably read.
