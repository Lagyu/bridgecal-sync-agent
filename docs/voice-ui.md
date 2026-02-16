# Voice / natural language input (Phase 2)

The CEO requested “voice” for:
- Checking events in a time range
- Creating new events

Because browser speech APIs are inconsistent across platforms, the recommended MVP approach is:

- Provide a tiny web UI (PWA) that accepts a **single-line command**.
- On each device, use the OS dictation feature to turn voice into text.
- The command parser converts the text to:
  - a query (read events)
  - or an insertion (create event)

This can be implemented as a separate module/service later. It is **out of scope** for the sync-agent MVP.
