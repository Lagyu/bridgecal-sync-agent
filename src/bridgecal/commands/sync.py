from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path

import typer

from ..config import load_config
from ..google_client import GoogleClient
from ..logging_config import configure_logging
from ..outlook_client import OutlookClient
from ..sync.engine import SyncEngine
from ..sync.mapping import MappingStore

logger = logging.getLogger(__name__)
ONCE_OPTION = typer.Option(False, "--once", help="Run a single sync pass and exit.")
DAEMON_OPTION = typer.Option(False, "--daemon", help="Run continuously.")
INTERVAL_OPTION = typer.Option(None, "--interval", help="Polling interval in seconds.")
CONFIG_OPTION = typer.Option(None, "--config", help="Path to config.toml")
DEBUG_OPTION = typer.Option(False, "--debug", help="Enable debug logging.")


def sync(
    once: bool = ONCE_OPTION,
    daemon: bool = DAEMON_OPTION,
    interval: int | None = INTERVAL_OPTION,
    config: Path | None = CONFIG_OPTION,
    debug: bool = DEBUG_OPTION,
) -> None:
    """Sync Outlook ↔ Google Calendar."""
    if once and daemon:
        raise typer.BadParameter("Use either --once or --daemon, not both.")

    cfg = load_config(config)
    if interval is not None:
        if interval <= 0:
            raise typer.BadParameter("--interval must be greater than 0")
        cfg = replace(cfg, sync=replace(cfg.sync, interval_seconds=interval))

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(cfg.data_dir / "bridgecal.log", level="DEBUG" if debug else "INFO")

    store = MappingStore(cfg.data_dir / "state.db")
    engine = SyncEngine(
        outlook=OutlookClient(),
        google=GoogleClient(
            calendar_id=cfg.google.calendar_id,
            client_secret_path=cfg.google.client_secret_path,
            token_path=cfg.google.token_path,
        ),
        store=store,
    )

    run_daemon = daemon or not once

    def run_one_pass() -> None:
        stats = engine.run_once(
            past_days=cfg.outlook.past_days,
            future_days=cfg.outlook.future_days,
        )
        typer.echo(
            "sync: "
            f"outlook={stats.outlook_scanned} "
            f"google={stats.google_scanned} "
            f"create_g={stats.created_in_google} "
            f"update_g={stats.updated_in_google} "
            f"delete_g={stats.deleted_in_google} "
            f"create_o={stats.created_in_outlook} "
            f"update_o={stats.updated_in_outlook} "
            f"delete_o={stats.deleted_in_outlook}",
        )

    try:
        if not run_daemon:
            try:
                run_one_pass()
            except Exception:
                logger.exception("Sync pass failed")
                raise typer.Exit(code=4) from None
            raise typer.Exit(code=0)

        while True:
            try:
                run_one_pass()
            except Exception:
                logger.exception("Sync pass failed")
            time.sleep(cfg.sync.interval_seconds)
    except KeyboardInterrupt:
        logger.info("Sync daemon interrupted by user")
    finally:
        store.close()
