# ExecPlan: Availability Thinking Model Selector + Streamed LLM Log

## Goal
Let users pick a local reasoning model for GUI availability checks and stream raw `<think>...</think>` plus final `<answer>...</answer>` output live in the popup.

## Non-goals
- Changing sync engine behavior
- Creating events from natural language
- Remote/cloud LLM integration

## Current behavior
- Availability popup runs a background parse and only shows final availability result (`src/bridgecal/gui_app.py`).
- Parser model is implicit from environment/default and not selectable in popup (`src/bridgecal/availability.py`).
- No live model-output trace is shown to the user.

## Proposed behavior
- Popup includes model selector with:
  - `LiquidAI/LFM2.5-1.2B-Thinking`
  - `Qwen/Qwen3-1.7B`
- Availability parsing is forced to thinking mode with `max_new_tokens=16384`.
- Popup shows a dedicated read-only log box streaming parser output while generation runs.

## Design
- Extend parser entrypoints to accept:
  - explicit `model_id`
  - explicit `max_new_tokens`
  - `force_thinking`
  - streaming callback (`on_model_output_chunk`)
- Add streaming generation path via `transformers.TextIteratorStreamer` with fallback to existing non-streaming call.
- Wire GUI popup to:
  - capture model selection
  - pass parser options
  - collect streamed chunks via queue + timer into a new log box.

## Implementation steps (checklist)
- [x] Extend availability parser API for model override, forced thinking, token override, and streaming callback.
- [x] Add transformer streamer generation path with safe fallback.
- [x] Add GUI model selector and streamed LLM log box in availability popup.
- [x] Force popup availability parse to thinking mode and max tokens 16384.
- [x] Update docs and tests.

## Testing plan
- Unit tests for parser override forwarding and streamed callback path.
- Lint/type/tests:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy src tests`
  - `uv run pytest -q`
- Manual GUI test:
  - Open availability popup
  - Pick each model and run check
  - Confirm `<think>` and `<answer>` appear incrementally in log box
  - Confirm final availability result remains correct

## Rollout / operations
- Existing CLI behavior remains backward compatible (new params optional).
- If issues appear, revert popup to existing parse call and disable streaming path.

## Decision log
- 2026-02-17: Implemented streamed parser trace in popup to improve transparency/debuggability for reasoning models.
