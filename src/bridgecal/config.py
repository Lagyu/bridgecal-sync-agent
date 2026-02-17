from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .paths import default_data_dir


@dataclass(frozen=True)
class OutlookConfig:
    # Reserved for future: profile selection, folder name, etc.
    past_days: int = 30
    future_days: int = 180


@dataclass(frozen=True)
class GoogleConfig:
    calendar_id: str
    client_secret_path: Path
    token_path: Path
    insecure_tls_skip_verify: bool = True


@dataclass(frozen=True)
class SyncConfig:
    interval_seconds: int = 120
    redaction_mode: str = "none"  # none|summary_only (future)


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    outlook: OutlookConfig
    google: GoogleConfig
    sync: SyncConfig


def load_config(path: Path | None = None) -> AppConfig:
    """Load config.toml.

    If `path` is None, load from the default data dir.
    """
    data_dir = default_data_dir()
    cfg_path = path or (data_dir / "config.toml")
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8-sig"))

    data_dir = Path(raw.get("data_dir", str(data_dir)))

    outlook_raw = raw.get("outlook", {})
    outlook = OutlookConfig(
        past_days=int(outlook_raw.get("past_days", 30)),
        future_days=int(outlook_raw.get("future_days", 180)),
    )

    google_raw = raw.get("google", {})
    client_secret = Path(google_raw.get("client_secret_path", "google_client_secret.json"))
    token_path = Path(google_raw.get("token_path", "google_token.json"))
    insecure_tls_skip_verify = _parse_bool(google_raw.get("insecure_tls_skip_verify"), default=True)
    if not client_secret.is_absolute():
        client_secret = data_dir / client_secret
    if not token_path.is_absolute():
        token_path = data_dir / token_path

    google = GoogleConfig(
        calendar_id=str(google_raw["calendar_id"]),
        client_secret_path=client_secret,
        token_path=token_path,
        insecure_tls_skip_verify=insecure_tls_skip_verify,
    )

    sync_raw = raw.get("sync", {})
    sync = SyncConfig(
        interval_seconds=int(sync_raw.get("interval_seconds", 120)),
        redaction_mode=str(sync_raw.get("redaction_mode", "none")),
    )

    return AppConfig(data_dir=data_dir, outlook=outlook, google=google, sync=sync)


def _parse_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default
