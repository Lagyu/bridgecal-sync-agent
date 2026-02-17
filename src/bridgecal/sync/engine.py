from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .mapping import MappingRow, MappingStore
from .models import CanonicalEvent, compute_fingerprint

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    outlook_scanned: int = 0
    google_scanned: int = 0
    outlook_sources: int = 0
    google_sources: int = 0
    outlook_mirrors: int = 0
    google_mirrors: int = 0
    created_in_google: int = 0
    updated_in_google: int = 0
    deleted_in_google: int = 0
    created_in_outlook: int = 0
    updated_in_outlook: int = 0
    deleted_in_outlook: int = 0


class OutlookPort(Protocol):
    def list_events(
        self, window_start: datetime, window_end: datetime
    ) -> Sequence[CanonicalEvent]: ...

    def upsert_mirror(self, source: CanonicalEvent) -> str:
        """Create/update an Outlook mirror event and return its outlook_id."""
        ...

    def delete_event(self, outlook_id: str) -> None: ...


class GooglePort(Protocol):
    def list_events(
        self, window_start: datetime, window_end: datetime
    ) -> Sequence[CanonicalEvent]: ...

    def upsert_mirror(self, source: CanonicalEvent) -> str:
        """Create/update a Google mirror event and return its google_event_id."""
        ...

    def delete_event(self, google_event_id: str) -> None: ...


class SyncEngine:
    def __init__(self, outlook: OutlookPort, google: GooglePort, store: MappingStore) -> None:
        self.outlook = outlook
        self.google = google
        self.store = store

    def run_once(self, past_days: int, future_days: int, now: datetime | None = None) -> SyncStats:
        now = now or datetime.now(UTC)
        window_start = now - timedelta(days=past_days)
        window_end = now + timedelta(days=future_days)

        outlook_events = list(self.outlook.list_events(window_start, window_end))
        google_events = list(self.google.list_events(window_start, window_end))

        stats = SyncStats(outlook_scanned=len(outlook_events), google_scanned=len(google_events))

        outlook_all = self._index_events(outlook_events)
        google_all = self._index_events(google_events)
        outlook_sources = {k: v for k, v in outlook_all.items() if not v.is_mirror}
        google_sources = {k: v for k, v in google_all.items() if not v.is_mirror}
        stats.outlook_sources = len(outlook_sources)
        stats.google_sources = len(google_sources)
        stats.outlook_mirrors = len(outlook_all) - len(outlook_sources)
        stats.google_mirrors = len(google_all) - len(google_sources)

        consumed_outlook_sources: set[str] = set()
        consumed_google_sources: set[str] = set()

        for row in self.store.list_all():
            if row.origin == "outlook":
                self._reconcile_outlook_origin(
                    row=row,
                    stats=stats,
                    outlook_sources=outlook_sources,
                    google_all=google_all,
                    consumed_outlook_sources=consumed_outlook_sources,
                )
                continue

            self._reconcile_google_origin(
                row=row,
                stats=stats,
                google_sources=google_sources,
                outlook_all=outlook_all,
                consumed_google_sources=consumed_google_sources,
            )

        for source in outlook_sources.values():
            if source.source_id in consumed_outlook_sources:
                continue
            google_id = self.google.upsert_mirror(source)
            self.store.upsert(
                MappingRow(
                    outlook_id=source.source_id,
                    google_id=google_id,
                    origin="outlook",
                    last_outlook_fp=compute_fingerprint(source),
                    last_outlook_modified=self._dt_key(source.last_modified),
                )
            )
            stats.created_in_google += 1

        for source in google_sources.values():
            if source.source_id in consumed_google_sources:
                continue
            outlook_id = self.outlook.upsert_mirror(source)
            self.store.upsert(
                MappingRow(
                    outlook_id=outlook_id,
                    google_id=source.source_id,
                    origin="google",
                    last_google_fp=compute_fingerprint(source),
                    last_google_updated=self._dt_key(source.last_modified),
                )
            )
            stats.created_in_outlook += 1

        logger.info(
            "sync summary outlook_scanned=%s google_scanned=%s outlook_sources=%s google_sources=%s outlook_mirrors=%s google_mirrors=%s create_g=%s update_g=%s delete_g=%s create_o=%s update_o=%s delete_o=%s",
            stats.outlook_scanned,
            stats.google_scanned,
            stats.outlook_sources,
            stats.google_sources,
            stats.outlook_mirrors,
            stats.google_mirrors,
            stats.created_in_google,
            stats.updated_in_google,
            stats.deleted_in_google,
            stats.created_in_outlook,
            stats.updated_in_outlook,
            stats.deleted_in_outlook,
        )
        return stats

    def _reconcile_outlook_origin(
        self,
        *,
        row: MappingRow,
        stats: SyncStats,
        outlook_sources: dict[str, CanonicalEvent],
        google_all: dict[str, CanonicalEvent],
        consumed_outlook_sources: set[str],
    ) -> None:
        source = outlook_sources.get(row.outlook_id)
        if source is None:
            self.google.delete_event(row.google_id)
            self.store.delete_pair(row.outlook_id, row.google_id)
            stats.deleted_in_google += 1
            return

        consumed_outlook_sources.add(source.source_id)
        target = google_all.get(row.google_id)

        source_changed = self._event_changed(source, row.last_outlook_fp, row.last_outlook_modified)
        has_target_baseline = bool(row.last_google_fp or row.last_google_updated)
        target_changed = (
            target is not None
            and has_target_baseline
            and self._event_changed(
                target,
                row.last_google_fp,
                row.last_google_updated,
            )
        )

        write_target = target is None
        if source_changed:
            write_target = True
            if target is not None and target_changed and not self._source_wins(source, target):
                write_target = False
                logger.info(
                    "conflict resolved winner=google pair_outlook=%s pair_google=%s",
                    row.outlook_id,
                    row.google_id,
                )

        google_id = row.google_id
        if write_target:
            google_id = self.google.upsert_mirror(source)
            if target is None:
                stats.created_in_google += 1
            else:
                stats.updated_in_google += 1
            if google_id != row.google_id:
                self.store.delete_pair(row.outlook_id, row.google_id)

        current_target = google_all.get(google_id)
        self.store.upsert(
            MappingRow(
                outlook_id=source.source_id,
                google_id=google_id,
                origin="outlook",
                last_outlook_fp=compute_fingerprint(source),
                last_google_fp=compute_fingerprint(current_target)
                if current_target
                else row.last_google_fp,
                last_outlook_modified=self._dt_key(source.last_modified),
                last_google_updated=self._dt_key(current_target.last_modified)
                if current_target
                else row.last_google_updated,
            )
        )

    def _reconcile_google_origin(
        self,
        *,
        row: MappingRow,
        stats: SyncStats,
        google_sources: dict[str, CanonicalEvent],
        outlook_all: dict[str, CanonicalEvent],
        consumed_google_sources: set[str],
    ) -> None:
        source = google_sources.get(row.google_id)
        if source is None:
            self.outlook.delete_event(row.outlook_id)
            self.store.delete_pair(row.outlook_id, row.google_id)
            stats.deleted_in_outlook += 1
            return

        consumed_google_sources.add(source.source_id)
        target = outlook_all.get(row.outlook_id)

        source_changed = self._event_changed(source, row.last_google_fp, row.last_google_updated)
        has_target_baseline = bool(row.last_outlook_fp or row.last_outlook_modified)
        target_changed = (
            target is not None
            and has_target_baseline
            and self._event_changed(
                target,
                row.last_outlook_fp,
                row.last_outlook_modified,
            )
        )

        write_target = target is None
        if source_changed:
            write_target = True
            if target is not None and target_changed and not self._source_wins(source, target):
                write_target = False
                logger.info(
                    "conflict resolved winner=outlook pair_outlook=%s pair_google=%s",
                    row.outlook_id,
                    row.google_id,
                )

        outlook_id = row.outlook_id
        if write_target:
            outlook_id = self.outlook.upsert_mirror(source)
            if target is None:
                stats.created_in_outlook += 1
            else:
                stats.updated_in_outlook += 1
            if outlook_id != row.outlook_id:
                self.store.delete_pair(row.outlook_id, row.google_id)

        current_target = outlook_all.get(outlook_id)
        self.store.upsert(
            MappingRow(
                outlook_id=outlook_id,
                google_id=source.source_id,
                origin="google",
                last_outlook_fp=compute_fingerprint(current_target)
                if current_target
                else row.last_outlook_fp,
                last_google_fp=compute_fingerprint(source),
                last_outlook_modified=self._dt_key(current_target.last_modified)
                if current_target
                else row.last_outlook_modified,
                last_google_updated=self._dt_key(source.last_modified),
            )
        )

    def _index_events(self, events: Sequence[CanonicalEvent]) -> dict[str, CanonicalEvent]:
        indexed: dict[str, CanonicalEvent] = {}
        for event in events:
            previous = indexed.get(event.source_id)
            if previous is None:
                indexed[event.source_id] = event
                continue
            if self._source_wins(event, previous):
                indexed[event.source_id] = event
        return indexed

    def _event_changed(self, event: CanonicalEvent, last_fp: str, last_modified: str) -> bool:
        current_fp = compute_fingerprint(event)
        if not last_fp:
            return True
        if current_fp != last_fp:
            return True

        prev_ts = self._parse_dt(last_modified)
        if event.last_modified is None:
            return False
        if prev_ts is None:
            return True
        return event.last_modified > prev_ts

    def _source_wins(self, source: CanonicalEvent, target: CanonicalEvent) -> bool:
        source_ts = source.last_modified
        target_ts = target.last_modified
        if source_ts is not None and target_ts is not None:
            if source_ts > target_ts:
                return True
            if source_ts < target_ts:
                return False
            return source.origin == "outlook"

        return source.origin == "outlook"

    def _dt_key(self, value: datetime | None) -> str:
        if value is None:
            return ""
        return value.isoformat()

    def _parse_dt(self, value: str) -> datetime | None:
        if not value:
            return None
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
