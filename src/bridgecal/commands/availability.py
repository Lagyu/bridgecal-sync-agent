from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from ..availability import AvailabilityResult, check_availability, parse_natural_time_range
from ..config import load_config
from ..google_client import GoogleClient
from ..logging_config import configure_logging
from ..outlook_client import OutlookClient

logger = logging.getLogger(__name__)

TEXT_OPTION = typer.Option(..., "--text", help="Natural language query, e.g. 明日の10時から17時")
LANG_OPTION = typer.Option(
    "ja",
    "--lang",
    help="Input language hint: ja or en",
)
CONFIG_OPTION = typer.Option(None, "--config", help="Path to config.toml")
DEBUG_OPTION = typer.Option(False, "--debug", help="Enable debug logging.")
JSON_OPTION = typer.Option(False, "--json", help="Emit machine-readable JSON output.")


def availability(
    text: str = TEXT_OPTION,
    lang: str = LANG_OPTION,
    config: Path | None = CONFIG_OPTION,
    debug: bool = DEBUG_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    """Check whether a requested time range is free in both Outlook and Google calendars."""
    normalized_lang = lang.strip().lower()
    if normalized_lang not in {"ja", "en"}:
        raise typer.BadParameter("--lang must be either 'ja' or 'en'.")

    cfg = load_config(config)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(cfg.data_dir / "bridgecal.log", level="DEBUG" if debug else "INFO")

    try:
        query_range = parse_natural_time_range(text, preferred_language=normalized_lang)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except RuntimeError as exc:
        typer.echo(f"[fail] Availability parser failed: {exc}", err=True)
        raise typer.Exit(code=4) from None

    try:
        outlook_events = list(OutlookClient().list_events(query_range.start, query_range.end))
        google_events = list(
            GoogleClient(
                calendar_id=cfg.google.calendar_id,
                client_secret_path=cfg.google.client_secret_path,
                token_path=cfg.google.token_path,
                insecure_tls_skip_verify=cfg.google.insecure_tls_skip_verify,
            ).list_events(query_range.start, query_range.end)
        )
    except Exception:
        logger.exception("Availability check failed")
        raise typer.Exit(code=4) from None

    result = check_availability(
        query_text=text,
        query_range=query_range,
        outlook_events=outlook_events,
        google_events=google_events,
    )
    if json_output:
        typer.echo(
            json.dumps(
                _to_json_payload(result),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        raise typer.Exit(code=0)

    typer.echo(
        "availability_window: "
        f"start={_isoformat(result.query_range.start)} "
        f"end={_isoformat(result.query_range.end)}"
    )
    typer.echo(
        "availability: "
        f"available={'true' if result.available else 'false'} "
        f"conflicts={len(result.conflicts)}"
    )
    for conflict in result.conflicts:
        typer.echo(
            "conflict: "
            f"origin={conflict.origin} "
            f"start={_isoformat(conflict.start)} "
            f"end={_isoformat(conflict.end)} "
            f"summary={json.dumps(conflict.summary, ensure_ascii=False)}"
        )

    raise typer.Exit(code=0)


def _to_json_payload(result: AvailabilityResult) -> dict[str, Any]:
    return {
        "query_text": result.query_text,
        "window": {
            "start": _isoformat(result.query_range.start),
            "end": _isoformat(result.query_range.end),
        },
        "available": result.available,
        "conflicts": [
            {
                "origin": conflict.origin,
                "source_id": conflict.source_id,
                "summary": conflict.summary,
                "start": _isoformat(conflict.start),
                "end": _isoformat(conflict.end),
                "all_day": conflict.all_day,
            }
            for conflict in result.conflicts
        ],
    }


def _isoformat(value: datetime) -> str:
    return value.isoformat()
