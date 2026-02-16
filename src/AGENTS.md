# src/ — Agent Instructions (Code)

## Code style
- Python 3.12+ only.
- Use type hints everywhere (mypy should pass).
- Prefer small, testable functions; keep side effects at the edges.
- Use `ruff` formatting and lint rules (no manual formatting debates).

## Error handling
- Wrap Outlook COM calls carefully; COM is brittle and exceptions are often opaque.
- Retries are allowed for transient Google API failures.
- Never crash the daemon on a single bad event; log and continue.

## Privacy
- Do not log event descriptions by default.
- Never include credentials in logs or exceptions.

## Testing
- Unit test the sync engine using fake clients (no real Outlook/Google calls).
- Keep integration tests optional behind an environment flag.
