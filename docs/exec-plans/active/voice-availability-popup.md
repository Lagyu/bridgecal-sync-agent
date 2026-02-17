# ExecPlan: Voice Availability Popup (CPU STT)

## Goal
Add a dedicated GUI popup where the user can input a time range by text or voice and check availability against both Outlook and Google calendars.

## Non-goals
- Event creation from natural language
- Continuous/streaming voice recognition
- Mobile/web UI

## Current behavior
- GUI supports setup, doctor, manual sync, and scheduler management (`src/bridgecal/gui_app.py`).
- No built-in availability-check workflow.
- No built-in local speech-to-text workflow.

## Proposed behavior
- Add `bridgecal availability` CLI command for text-based availability checks.
- Add a popup in GUI for:
  - text input (natural language range)
  - microphone recording + local speech-to-text
  - availability result display with conflict details
- Use `faster-whisper` on CPU for STT backend.

## Design
- New module `src/bridgecal/availability.py`
  - parse time ranges using local LFM2.5 structured JSON output
  - evaluate overlap against canonical events from both calendars
- New module `src/bridgecal/voice_stt.py`
  - record short mic clip
  - transcribe locally with cached `faster-whisper` model on CPU
- GUI (`src/bridgecal/gui_app.py`)
  - add dedicated popup action
  - run long operations in background thread
  - show busy/loading feedback and prevent double-click

## Implementation steps (checklist)
- [x] Add availability parser/checking core module
- [x] Add CPU STT module with faster-whisper backend
- [x] Add `bridgecal availability` command
- [x] Add GUI popup for text/voice input and results
- [ ] Finalize docs and run validation suite

## Testing plan
- Unit tests for natural-language parsing and overlap logic.
- Unit tests for STT dependency guard rails.
- Manual GUI test:
  - Open popup
  - Input text query and run check
  - Record voice and confirm transcript is inserted
  - Validate busy/ready status and conflict output

## Rollout / operations
- Requires additional Python deps (`faster-whisper`, `sounddevice`, `soundfile`, `transformers`, `torch`).
- First voice use may be slower due to model download/load; model is cached in-process.
- Revert by removing new command and popup action; sync behavior is unaffected.

## Decision log
- 2026-02-17: Chose `faster-whisper` for CPU-first local Japanese STT accuracy/performance tradeoff.
- 2026-02-17: Switched parser integration from API-based approach to local LFM2.5 model usage.
- 2026-02-17: Switched local parser runtime from `transformers` to `llama.cpp` with schema-constrained JSON output.
- 2026-02-17: Removed non-LFM fallback; parsing now requires local LFM output.
- 2026-02-17: Migrated parser runtime back to `transformers` for local LFM model compatibility.
