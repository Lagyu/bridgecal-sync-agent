from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Origin = Literal["outlook", "google"]


@dataclass(frozen=True)
class EventTime:
    """Represents either an all-day or timed event."""

    start_dt: datetime | None = None
    end_dt: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None  # exclusive, like Google all-day

    @property
    def is_all_day(self) -> bool:
        return self.start_date is not None


@dataclass(frozen=True)
class CanonicalEvent:
    origin: Origin
    source_id: str

    time: EventTime
    summary: str
    location: str = ""
    description: str = ""

    busy: bool = True
    private: bool = True

    last_modified: datetime | None = None
    fingerprint: str = ""
    mirror_origin: Origin | None = None
    mirror_source_id: str = ""

    @property
    def is_mirror(self) -> bool:
        return self.mirror_origin is not None


def _dt_key(value: datetime | None) -> str:
    return value.isoformat() if value else ""


def _date_key(value: date | None) -> str:
    return value.isoformat() if value else ""


def compute_fingerprint(event: CanonicalEvent) -> str:
    if event.fingerprint:
        return event.fingerprint

    payload = {
        "start_dt": _dt_key(event.time.start_dt),
        "end_dt": _dt_key(event.time.end_dt),
        "start_date": _date_key(event.time.start_date),
        "end_date": _date_key(event.time.end_date),
        "summary": event.summary,
        "location": event.location,
        "description": event.description,
        "busy": event.busy,
        "private": event.private,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
