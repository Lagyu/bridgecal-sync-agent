from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import typer

from ..config import load_config
from ..google_client import GoogleClient
from ..logging_config import configure_logging
from ..outlook_client import OutlookClient
from ..sync.mapping import MappingStore

logger = logging.getLogger(__name__)
CONFIG_OPTION = typer.Option(None, "--config", help="Path to config.toml")
DEBUG_OPTION = typer.Option(False, "--debug", help="Enable debug logging.")


def doctor(
    config: Path | None = CONFIG_OPTION,
    debug: bool = DEBUG_OPTION,
) -> None:
    """Validate Outlook, Google auth, and local state persistence."""
    cfg = load_config(config)

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(cfg.data_dir / "bridgecal.log", level="DEBUG" if debug else "INFO")

    failures: list[tuple[int, str]] = []

    try:
        OutlookClient().health_check()
        typer.echo("[ok] Outlook COM access")
    except Exception as exc:
        logger.exception("Outlook doctor check failed")
        code = 2 if "pywin32" in str(exc).lower() else 4
        failures.append((code, f"Outlook check failed: {exc}"))

    try:
        GoogleClient(
            calendar_id=cfg.google.calendar_id,
            client_secret_path=cfg.google.client_secret_path,
            token_path=cfg.google.token_path,
        ).health_check()
        typer.echo("[ok] Google Calendar auth + access")
    except Exception as exc:
        logger.exception("Google doctor check failed")
        failures.append((_classify_google_failure(exc), f"Google check failed: {exc}"))

    store: MappingStore | None = None
    try:
        store = MappingStore(cfg.data_dir / "state.db")
        key = "doctor.last_write"
        now = datetime.now(UTC).isoformat()
        store.kv_set(key, now)
        observed = store.kv_get(key)
        if observed != now:
            raise RuntimeError("SQLite roundtrip mismatch")
        typer.echo("[ok] SQLite state.db writable")
    except Exception as exc:
        logger.exception("SQLite doctor check failed")
        failures.append((2, f"SQLite check failed: {exc}"))
    finally:
        if store is not None:
            store.close()

    if not failures:
        typer.echo("doctor: all checks passed")
        raise typer.Exit(code=0)

    highest_priority = 4
    for code, message in failures:
        typer.echo(f"[fail] {message}", err=True)
        if code == 2:
            highest_priority = 2
            continue
        if code == 3 and highest_priority != 2:
            highest_priority = 3

    raise typer.Exit(code=highest_priority)


def _classify_google_failure(exc: Exception) -> int:
    if isinstance(exc, FileNotFoundError):
        return 2

    text = str(exc).lower()
    if "invalid_grant" in text or "unauthorized" in text or "token" in text:
        return 3
    if "client secret" in text or "credentials" in text:
        return 2
    return 4
