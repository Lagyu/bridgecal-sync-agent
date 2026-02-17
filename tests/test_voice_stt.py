from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

import bridgecal.voice_stt as voice_stt_module


def test_transcribe_audio_file_requires_faster_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = voice_stt_module._DependencyLoadResult(module=None)

    def fake_loader(module_name: str) -> voice_stt_module._DependencyLoadResult:
        if module_name == "faster_whisper":
            return missing
        return voice_stt_module._DependencyLoadResult(module=object())

    monkeypatch.setattr(voice_stt_module, "_load_optional_dependency", fake_loader)

    with pytest.raises(RuntimeError, match="faster-whisper is unavailable"):
        voice_stt_module.transcribe_audio_file(
            audio_path=Path("dummy.wav"),
            language="ja",
        )


def test_transcribe_microphone_requires_recording_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = voice_stt_module._DependencyLoadResult(module=None)

    def fake_loader(module_name: str) -> voice_stt_module._DependencyLoadResult:
        if module_name in {"sounddevice", "soundfile"}:
            return missing
        return voice_stt_module._DependencyLoadResult(module=object())

    monkeypatch.setattr(voice_stt_module, "_load_optional_dependency", fake_loader)

    with pytest.raises(RuntimeError, match="Microphone recording dependencies are unavailable"):
        voice_stt_module.transcribe_microphone(language="ja")


def test_transcribe_audio_file_surfaces_dependency_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import_error = OSError(
        "[WinError 1114] A dynamic link library (DLL) initialization routine failed."
    )

    def fake_loader(module_name: str) -> voice_stt_module._DependencyLoadResult:
        if module_name == "faster_whisper":
            return voice_stt_module._DependencyLoadResult(module=None, error=import_error)
        return voice_stt_module._DependencyLoadResult(module=object())

    monkeypatch.setattr(voice_stt_module, "_load_optional_dependency", fake_loader)

    with pytest.raises(RuntimeError, match="WinError 1114"):
        voice_stt_module.transcribe_audio_file(
            audio_path=Path("dummy.wav"),
            language="ja",
        )


def test_record_microphone_to_wav_uses_full_duration_without_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSoundDevice:
        def __init__(self) -> None:
            self.stop_called = False
            self.wait_called = False

        def rec(
            self,
            frame_count: int,
            *,
            samplerate: int,
            channels: int,
            dtype: str,
        ) -> list[list[float]]:
            assert samplerate == 8000
            assert channels == 1
            assert dtype == "float32"
            return [[0.25] for _ in range(frame_count)]

        def wait(self) -> None:
            self.wait_called = True

        def stop(self) -> None:
            self.stop_called = True

    class FakeSoundFile:
        def __init__(self) -> None:
            self.write_payload: Any = None

        def write(self, path: str, payload: Any, sample_rate: int) -> None:
            assert path.endswith(".wav")
            assert sample_rate == 8000
            self.write_payload = payload

    fake_sounddevice = FakeSoundDevice()
    fake_soundfile = FakeSoundFile()

    monkeypatch.setattr(
        voice_stt_module,
        "_microphone_modules",
        lambda: (fake_sounddevice, fake_soundfile),
    )

    output = voice_stt_module._record_microphone_to_wav(seconds=1.0, sample_rate=8000)
    output.unlink(missing_ok=True)

    assert fake_sounddevice.wait_called is True
    assert fake_sounddevice.stop_called is False
    assert isinstance(fake_soundfile.write_payload, list)
    assert len(fake_soundfile.write_payload) == 8000


def test_record_microphone_to_wav_stops_early_when_stop_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSoundDevice:
        def __init__(self) -> None:
            self.stop_called = False

        def rec(
            self,
            frame_count: int,
            *,
            samplerate: int,
            channels: int,
            dtype: str,
        ) -> list[list[float]]:
            assert frame_count == 8000
            assert samplerate == 8000
            assert channels == 1
            assert dtype == "float32"
            return [[0.5] for _ in range(frame_count)]

        def wait(self) -> None:
            return None

        def stop(self) -> None:
            self.stop_called = True

    class FakeSoundFile:
        def __init__(self) -> None:
            self.write_payload: Any = None

        def write(self, path: str, payload: Any, sample_rate: int) -> None:
            assert path.endswith(".wav")
            assert sample_rate == 8000
            self.write_payload = payload

    fake_sounddevice = FakeSoundDevice()
    fake_soundfile = FakeSoundFile()
    stop_event = threading.Event()
    stop_event.set()

    monkeypatch.setattr(
        voice_stt_module,
        "_microphone_modules",
        lambda: (fake_sounddevice, fake_soundfile),
    )

    output = voice_stt_module._record_microphone_to_wav(
        seconds=1.0,
        sample_rate=8000,
        stop_event=stop_event,
    )
    output.unlink(missing_ok=True)

    assert fake_sounddevice.stop_called is True
    assert isinstance(fake_soundfile.write_payload, list)
    assert len(fake_soundfile.write_payload) == 1
