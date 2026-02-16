# BridgeCal ExecPlans (Planning Template)

Use an ExecPlan when implementing a complex feature or refactor (recurrences, conflict policy changes, schema changes, etc.).

An ExecPlan must be **self-contained**: a new contributor should be able to implement it using only the ExecPlan plus the current working tree.

## Template

Copy this template into `docs/exec-plans/active/<name>.md`:

---

# ExecPlan: <short title>

## Goal
Describe what will be delivered and why.

## Non-goals
Explicitly list what is out of scope.

## Current behavior
What happens today (with file references).

## Proposed behavior
Describe the new behavior in detail.

## Design
- Data model changes (tables, fields, migrations)
- Algorithm changes
- Edge cases

## Implementation steps (checklist)
- [ ] Step 1 ...
- [ ] Step 2 ...
- [ ] Step 3 ...

## Testing plan
- Unit tests
- Integration tests (if any)
- Manual test script

## Rollout / operations
- Backward compatibility
- How to revert

## Decision log
Append dated notes when decisions change.

---
