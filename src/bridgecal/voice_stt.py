from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from importlib import import_module, util
from pathlib import Path
from threading import Event, Lock
from typing import Any


@dataclass(frozen=True)
class _DependencyLoadResult:
    module: Any | None
    error: Exception | None = None


_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}
_MODEL_LOCK = Lock()
_DEPENDENCY_CACHE: dict[str, _DependencyLoadResult] = {}
_DEPENDENCY_LOCK = Lock()


def transcribe_microphone(
    *,
    language: str,
    seconds: float = 7.0,
    sample_rate: int = 16_000,
    model_size: str | None = None,
    compute_type: str | None = None,
    stop_event: Event | None = None,
) -> str:
    audio_path = _record_microphone_to_wav(
        seconds=seconds,
        sample_rate=sample_rate,
        stop_event=stop_event,
    )
    try:
        return transcribe_audio_file(
            audio_path,
            language=language,
            model_size=model_size,
            compute_type=compute_type,
        )
    finally:
        audio_path.unlink(missing_ok=True)


def transcribe_audio_file(
    audio_path: Path,
    *,
    language: str,
    model_size: str | None = None,
    compute_type: str | None = None,
) -> str:
    model = _whisper_model(
        model_size=model_size or _default_model_size(),
        compute_type=compute_type or _default_compute_type(),
    )
    segments, _ = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        best_of=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    text_parts = [str(segment.text).strip() for segment in segments if str(segment.text).strip()]
    text = " ".join(text_parts).strip()
    if not text:
        raise RuntimeError("No speech could be recognized from the recording.")
    return text


def _record_microphone_to_wav(
    *,
    seconds: float,
    sample_rate: int,
    stop_event: Event | None = None,
) -> Path:
    sounddevice_module, soundfile_module = _microphone_modules()
    if seconds <= 0:
        raise RuntimeError("Recording duration must be greater than zero.")
    if sample_rate < 8000:
        raise RuntimeError("Sample rate is too low for speech recognition.")

    frame_count = int(seconds * sample_rate)
    if frame_count <= 0:
        raise RuntimeError("Recording duration produced zero audio frames.")

    recording = sounddevice_module.rec(
        frame_count,
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )
    frames_to_write = frame_count
    if stop_event is None:
        sounddevice_module.wait()
    else:
        started_at = time.monotonic()
        deadline = started_at + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if stop_event.wait(timeout=min(0.05, remaining)):
                elapsed = max(0.0, time.monotonic() - started_at)
                frames_to_write = max(1, min(frame_count, int(elapsed * sample_rate)))
                sounddevice_module.stop()
                break
        sounddevice_module.wait()
        if frames_to_write < frame_count:
            recording = recording[:frames_to_write]

    fd, temp_file_path = tempfile.mkstemp(
        prefix="bridgecal-voice-",
        suffix=".wav",
    )
    os.close(fd)
    output_path = Path(temp_file_path)

    soundfile_module.write(str(output_path), recording, sample_rate)
    return output_path


def _whisper_model(*, model_size: str, compute_type: str) -> Any:
    faster_whisper_module = _require_dependency("faster_whisper")

    cache_key = (model_size, "cpu", compute_type)
    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(cache_key)
        if model is None:
            model_class = getattr(faster_whisper_module, "WhisperModel", None)
            if model_class is None:
                raise RuntimeError(
                    "faster-whisper installation is invalid: WhisperModel not found."
                )
            model = model_class(
                model_size,
                device="cpu",
                compute_type=compute_type,
            )
            _MODEL_CACHE[cache_key] = model
    return model


def _default_model_size() -> str:
    value = os.environ.get("BRIDGECAL_STT_MODEL", "").strip()
    return value or "small"


def _default_compute_type() -> str:
    value = os.environ.get("BRIDGECAL_STT_COMPUTE_TYPE", "").strip()
    return value or "int8"


def _microphone_modules() -> tuple[Any, Any]:
    sounddevice_module = _require_dependency("sounddevice")
    soundfile_module = _require_dependency("soundfile")
    return sounddevice_module, soundfile_module


def _require_dependency(module_name: str) -> Any:
    loaded = _load_optional_dependency(module_name)
    if loaded.module is not None:
        return loaded.module

    dependency_guidance = (
        "Run `uv sync --reinstall-package torch --reinstall-package faster-whisper "
        "--reinstall-package ctranslate2 --reinstall-package sounddevice "
        "--reinstall-package soundfile --reinstall-package transformers`."
    )
    if module_name == "faster_whisper":
        message = "faster-whisper is unavailable. Install dependency 'faster-whisper' first."
    elif module_name in {"sounddevice", "soundfile"}:
        message = (
            "Microphone recording dependencies are unavailable. "
            "Install 'sounddevice' and 'soundfile'."
        )
    else:
        message = f"Dependency '{module_name}' is unavailable."

    detail = _format_dependency_error(module_name, loaded.error)
    raise RuntimeError(f"{message} {detail} {dependency_guidance}".strip())


def _load_optional_dependency(module_name: str) -> _DependencyLoadResult:
    if util.find_spec(module_name) is None:
        return _DependencyLoadResult(module=None)

    with _DEPENDENCY_LOCK:
        cached = _DEPENDENCY_CACHE.get(module_name)
        if cached is not None:
            return cached

        try:
            module = import_module(module_name)
        except Exception as exc:
            loaded = _DependencyLoadResult(module=None, error=exc)
        else:
            loaded = _DependencyLoadResult(module=module)

        _DEPENDENCY_CACHE[module_name] = loaded
        return loaded


def _format_dependency_error(module_name: str, error: Exception | None) -> str:
    if error is None:
        return ""
    return f"{module_name} import failed: {error.__class__.__name__}: {error}"
