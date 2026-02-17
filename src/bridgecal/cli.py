from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)

CONFIG_OPTION = typer.Option(None, "--config", help="Path to config.toml")
DEBUG_OPTION = typer.Option(False, "--debug", help="Enable debug logging.")
ONCE_OPTION = typer.Option(False, "--once", help="Run a single sync pass and exit.")
DAEMON_OPTION = typer.Option(False, "--daemon", help="Run continuously.")
INTERVAL_OPTION = typer.Option(None, "--interval", help="Polling interval in seconds.")


@app.command()
def doctor(
    config: Path | None = CONFIG_OPTION,
    debug: bool = DEBUG_OPTION,
) -> None:
    """Validate Outlook, Google auth, and local state persistence."""
    from .commands.doctor import doctor as doctor_command

    doctor_command(config=config, debug=debug)


@app.command()
def sync(
    once: bool = ONCE_OPTION,
    daemon: bool = DAEMON_OPTION,
    interval: int | None = INTERVAL_OPTION,
    config: Path | None = CONFIG_OPTION,
    debug: bool = DEBUG_OPTION,
) -> None:
    """Sync Outlook ↔ Google Calendar."""
    from .commands.sync import sync as sync_command

    sync_command(
        once=once,
        daemon=daemon,
        interval=interval,
        config=config,
        debug=debug,
    )


@app.command()
def gui(
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Launch the BridgeCal Windows GUI."""
    from .commands.gui import gui as gui_command

    gui_command(config=config)


@app.command()
def availability(
    text: str = typer.Option(
        ...,
        "--text",
        help="Natural language query, e.g. 明日の10時から17時",
    ),
    lang: str = typer.Option("ja", "--lang", help="Input language hint: ja or en"),
    config: Path | None = CONFIG_OPTION,
    debug: bool = DEBUG_OPTION,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Check whether a requested time range is free in both calendars."""
    from .commands.availability import availability as availability_command

    availability_command(
        text=text,
        lang=lang,
        config=config,
        debug=debug,
        json_output=json_output,
    )
