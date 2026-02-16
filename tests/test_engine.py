from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bridgecal.sync.engine import SyncEngine
from bridgecal.sync.mapping import MappingStore
from bridgecal.sync.models import CanonicalEvent, EventTime, Origin, compute_fingerprint

BASE = datetime(2026, 2, 16, 9, 0, tzinfo=UTC)


def _timed_event(
    *,
    origin: Origin,
    source_id: str,
    summary: str,
    start_offset_hours: int,
    mirror_origin: Origin | None = None,
    mirror_source_id: str = "",
    last_modified_offset_minutes: int = 0,
) -> CanonicalEvent:
    start = BASE + timedelta(hours=start_offset_hours)
    end = start + timedelta(hours=1)
    event = CanonicalEvent(
        origin=origin,
        source_id=source_id,
        time=EventTime(start_dt=start, end_dt=end),
        summary=summary,
        location="room",
        description="notes",
        busy=True,
        private=True,
        last_modified=start + timedelta(minutes=last_modified_offset_minutes),
        mirror_origin=mirror_origin,
        mirror_source_id=mirror_source_id,
    )
    return replace(event, fingerprint=compute_fingerprint(event))


class FakeOutlook:
    def __init__(self, events: list[CanonicalEvent]) -> None:
        self.events: dict[str, CanonicalEvent] = {event.source_id: event for event in events}
        self.upserted_from: list[str] = []
        self.deleted: list[str] = []

    def list_events(self, window_start: datetime, window_end: datetime) -> list[CanonicalEvent]:
        return list(self.events.values())

    def upsert_mirror(self, source: CanonicalEvent) -> str:
        self.upserted_from.append(source.source_id)
        for existing in self.events.values():
            if existing.mirror_origin == "google" and existing.mirror_source_id == source.source_id:
                updated = _timed_event(
                    origin="outlook",
                    source_id=existing.source_id,
                    summary=source.summary,
                    start_offset_hours=int((source.time.start_dt or BASE).hour - BASE.hour),
                    mirror_origin="google",
                    mirror_source_id=source.source_id,
                )
                self.events[existing.source_id] = updated
                return existing.source_id

        mirror_id = f"om-{source.source_id}"
        created = _timed_event(
            origin="outlook",
            source_id=mirror_id,
            summary=source.summary,
            start_offset_hours=int((source.time.start_dt or BASE).hour - BASE.hour),
            mirror_origin="google",
            mirror_source_id=source.source_id,
        )
        self.events[mirror_id] = created
        return mirror_id

    def delete_event(self, outlook_id: str) -> None:
        self.deleted.append(outlook_id)
        self.events.pop(outlook_id, None)


class FakeGoogle:
    def __init__(self, events: list[CanonicalEvent]) -> None:
        self.events: dict[str, CanonicalEvent] = {event.source_id: event for event in events}
        self.upserted_from: list[str] = []
        self.deleted: list[str] = []

    def list_events(self, window_start: datetime, window_end: datetime) -> list[CanonicalEvent]:
        return list(self.events.values())

    def upsert_mirror(self, source: CanonicalEvent) -> str:
        self.upserted_from.append(source.source_id)
        for existing in self.events.values():
            if (
                existing.mirror_origin == "outlook"
                and existing.mirror_source_id == source.source_id
            ):
                updated = _timed_event(
                    origin="google",
                    source_id=existing.source_id,
                    summary=source.summary,
                    start_offset_hours=int((source.time.start_dt or BASE).hour - BASE.hour),
                    mirror_origin="outlook",
                    mirror_source_id=source.source_id,
                )
                self.events[existing.source_id] = updated
                return existing.source_id

        mirror_id = f"gm-{source.source_id}"
        created = _timed_event(
            origin="google",
            source_id=mirror_id,
            summary=source.summary,
            start_offset_hours=int((source.time.start_dt or BASE).hour - BASE.hour),
            mirror_origin="outlook",
            mirror_source_id=source.source_id,
        )
        self.events[mirror_id] = created
        return mirror_id

    def delete_event(self, google_event_id: str) -> None:
        self.deleted.append(google_event_id)
        self.events.pop(google_event_id, None)


def _engine_with_store(
    outlook_events: list[CanonicalEvent],
    google_events: list[CanonicalEvent],
) -> tuple[
    SyncEngine,
    MappingStore,
    FakeOutlook,
    FakeGoogle,
    tempfile.TemporaryDirectory[str],
]:
    tempdir = tempfile.TemporaryDirectory()
    store = MappingStore(Path(tempdir.name) / "state.db")
    outlook = FakeOutlook(outlook_events)
    google = FakeGoogle(google_events)
    engine = SyncEngine(outlook, google, store)
    return engine, store, outlook, google, tempdir


def test_loop_prevention_skips_mirror_items() -> None:
    engine, store, outlook, google, tempdir = _engine_with_store(
        outlook_events=[
            _timed_event(
                origin="outlook", source_id="o-src", summary="Outlook source", start_offset_hours=1
            ),
            _timed_event(
                origin="outlook",
                source_id="o-mirror",
                summary="Mirror from Google",
                start_offset_hours=2,
                mirror_origin="google",
                mirror_source_id="g-src",
            ),
        ],
        google_events=[
            _timed_event(
                origin="google", source_id="g-src", summary="Google source", start_offset_hours=3
            ),
            _timed_event(
                origin="google",
                source_id="g-mirror",
                summary="Mirror from Outlook",
                start_offset_hours=4,
                mirror_origin="outlook",
                mirror_source_id="o-src",
            ),
        ],
    )
    try:
        stats = engine.run_once(past_days=1, future_days=1, now=BASE)

        assert stats.created_in_google == 1
        assert stats.created_in_outlook == 1
        assert outlook.upserted_from == ["g-src"]
        assert google.upserted_from == ["o-src"]
        assert len(store.list_all()) == 2
    finally:
        store.close()
        tempdir.cleanup()


def test_create_update_delete_both_directions() -> None:
    engine, store, outlook, google, tempdir = _engine_with_store(
        outlook_events=[
            _timed_event(
                origin="outlook", source_id="o1", summary="Outlook A", start_offset_hours=1
            ),
        ],
        google_events=[
            _timed_event(origin="google", source_id="g1", summary="Google A", start_offset_hours=2),
        ],
    )
    try:
        first = engine.run_once(past_days=1, future_days=1, now=BASE)
        assert first.created_in_google == 1
        assert first.created_in_outlook == 1
        assert len(store.list_all()) == 2

        outlook.events["o1"] = _timed_event(
            origin="outlook",
            source_id="o1",
            summary="Outlook Updated",
            start_offset_hours=1,
            last_modified_offset_minutes=15,
        )
        google.events["g1"] = _timed_event(
            origin="google",
            source_id="g1",
            summary="Google Updated",
            start_offset_hours=2,
            last_modified_offset_minutes=20,
        )

        second = engine.run_once(past_days=1, future_days=1, now=BASE)
        assert second.updated_in_google == 1
        assert second.updated_in_outlook == 1

        outlook.events.pop("o1")
        google.events.pop("g1")

        third = engine.run_once(past_days=1, future_days=1, now=BASE)
        assert third.deleted_in_google == 1
        assert third.deleted_in_outlook == 1
        assert store.list_all() == []
    finally:
        store.close()
        tempdir.cleanup()


def test_idempotent_on_second_run_without_changes() -> None:
    engine, store, outlook, google, tempdir = _engine_with_store(
        outlook_events=[
            _timed_event(origin="outlook", source_id="o1", summary="Outlook", start_offset_hours=1),
        ],
        google_events=[
            _timed_event(origin="google", source_id="g1", summary="Google", start_offset_hours=2),
        ],
    )
    try:
        first = engine.run_once(past_days=1, future_days=1, now=BASE)
        assert first.created_in_google == 1
        assert first.created_in_outlook == 1

        upserts_outlook_before = len(outlook.upserted_from)
        upserts_google_before = len(google.upserted_from)
        deletes_outlook_before = len(outlook.deleted)
        deletes_google_before = len(google.deleted)

        second = engine.run_once(past_days=1, future_days=1, now=BASE)

        assert second.created_in_google == 0
        assert second.updated_in_google == 0
        assert second.deleted_in_google == 0
        assert second.created_in_outlook == 0
        assert second.updated_in_outlook == 0
        assert second.deleted_in_outlook == 0
        assert len(outlook.upserted_from) == upserts_outlook_before
        assert len(google.upserted_from) == upserts_google_before
        assert len(outlook.deleted) == deletes_outlook_before
        assert len(google.deleted) == deletes_google_before
    finally:
        store.close()
        tempdir.cleanup()
