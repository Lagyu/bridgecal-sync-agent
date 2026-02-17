from __future__ import annotations

from importlib import import_module, util
from pathlib import Path

import typer

CONFIG_OPTION = typer.Option(None, "--config", help="Path to config.toml")


def gui(config: Path | None = CONFIG_OPTION) -> None:
    """Launch the BridgeCal Windows GUI."""
    _preload_gui_ml_runtime()

    try:
        from ..gui_app import launch_gui
    except ModuleNotFoundError as exc:
        typer.echo(
            "PyQt6 is required to launch the GUI. Install dependencies with `uv sync`.",
            err=True,
        )
        raise typer.Exit(code=2) from exc

    try:
        exit_code = launch_gui(config_path=config)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None
    raise typer.Exit(code=exit_code)


def _preload_gui_ml_runtime() -> None:
    """Best-effort preload of STT/runtime modules before importing PyQt GUI code.

    On some Windows environments, importing torch/ctranslate2 after Qt is initialized
    can fail with WinError 1114. Preloading here avoids that import order.
    """
    for module_name in ("torch", "ctranslate2", "faster_whisper"):
        if not _module_exists(module_name):
            continue
        try:
            _import_runtime_module(module_name)
        except Exception:
            # Voice/STT remains optional; GUI can still launch.
            return


def _module_exists(module_name: str) -> bool:
    return util.find_spec(module_name) is not None


def _import_runtime_module(module_name: str) -> None:
    import_module(module_name)
