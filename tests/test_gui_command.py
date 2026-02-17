from __future__ import annotations

import pytest

import bridgecal.commands.gui as gui_command


def test_preload_gui_ml_runtime_import_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(gui_command, "_module_exists", lambda _name: True)

    def fake_import(name: str) -> None:
        calls.append(name)

    monkeypatch.setattr(gui_command, "_import_runtime_module", fake_import)

    gui_command._preload_gui_ml_runtime()

    assert calls == ["torch", "ctranslate2", "faster_whisper"]


def test_preload_gui_ml_runtime_stops_after_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(gui_command, "_module_exists", lambda _name: True)

    def fake_import(name: str) -> None:
        calls.append(name)
        if name == "torch":
            raise OSError("WinError 1114")

    monkeypatch.setattr(gui_command, "_import_runtime_module", fake_import)

    gui_command._preload_gui_ml_runtime()

    assert calls == ["torch"]


def test_preload_gui_ml_runtime_skips_missing_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_module_exists(name: str) -> bool:
        return name == "torch"

    def fake_import(name: str) -> None:
        calls.append(name)

    monkeypatch.setattr(gui_command, "_module_exists", fake_module_exists)
    monkeypatch.setattr(gui_command, "_import_runtime_module", fake_import)

    gui_command._preload_gui_ml_runtime()

    assert calls == ["torch"]
