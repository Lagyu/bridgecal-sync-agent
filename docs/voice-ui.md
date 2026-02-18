# Voice / Natural Language Availability Check

BridgeCal now supports a local voice/text popup in the Windows GUI for checking whether a time range is free.

## Implemented flow

- Open GUI and click `空き時間チェック（音声/テキスト）` / `Check Availability (Voice/Text)`
- Enter text like `明日の10時から17時` (or English equivalent), or record voice
- Voice recording is capped at 7 seconds and can be stopped early from the same button
- In the popup, choose parser model:
  - `LiquidAI/LFM2.5-1.2B-Thinking`
  - `Qwen/Qwen3-1.7B`
- Availability parsing is forced to thinking mode with max output tokens `16384`
- A dedicated LLM log box streams `<think>...</think>` and final `<answer>...</answer>` output
- BridgeCal checks overlap against both Outlook and Google events in that range
- Result shows:
  - free/busy decision
  - conflict list (source + time + summary)

## Speech-to-text backend

- Backend: `faster-whisper`
- Mode: CPU (`int8` compute type by default)
- Model default: `small`
- Microphone capture: `sounddevice` + `soundfile`
- Time-range parsing: local thinking model via `transformers` (structured JSON output)

Environment overrides:

- `BRIDGECAL_STT_MODEL` (e.g. `small`, `medium`, `large-v3`)
- `BRIDGECAL_STT_COMPUTE_TYPE` (default `int8`)
- `BRIDGECAL_LFM25_LOCAL_MODEL` (default `LiquidAI/LFM2.5-1.2B-Instruct`)
- `BRIDGECAL_LFM25_LOCAL_DEVICE` (`cpu` or `auto`, default `cpu`)
- `BRIDGECAL_LFM25_LOCAL_TORCH_DTYPE` (default `float32`)
- `BRIDGECAL_LFM25_LOCAL_MAX_NEW_TOKENS` (default `220`)
- `BRIDGECAL_LFM25_ALLOW_REMOTE_CODE` (`false` by default; set `true` only if a chosen model
  explicitly requires remote code)

Note:
- In the GUI popup, model is selected in-UI and parsing is forced to thinking mode with `16384` max tokens.

## Notes

- First voice run can be slower because model loading/downloading may occur.
- Local LFM parsing requires `transformers`, `torch`, and a supported local model.
- If local LFM is unavailable or returns invalid JSON, parsing fails with an explicit error.
- Voice-based event creation is still out of scope.
