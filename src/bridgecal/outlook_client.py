from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, time
from importlib import import_module, util
from typing import Any

from .sync.models import CanonicalEvent, EventTime, compute_fingerprint

logger = logging.getLogger(__name__)

pythoncom = import_module("pythoncom") if util.find_spec("pythoncom") else None
win32_client = import_module("win32com.client") if util.find_spec("win32com.client") else None

OL_APPOINTMENT_ITEM = 1
OL_FOLDER_CALENDAR = 9
OL_BUSY = 2
OL_PRIVATE = 2
OL_NON_MEETING = 0
OL_USER_PROPERTY_TEXT = 1
MIRROR_ORIGIN_PROP = "BridgeCalOrigin"
MIRROR_GOOGLE_ID_PROP = "BridgeCalGoogleId"


class OutlookClient:
    """Outlook adapter backed by desktop COM automation."""

    def __init__(self) -> None:
        self._namespace: Any | None = None
        self._application: Any | None = None

    def list_events(self, window_start: datetime, window_end: datetime) -> Sequence[CanonicalEvent]:
        items = self._calendar_items(window_start, window_end)
        events: list[CanonicalEvent] = []
        for item in items:
            event = self._to_canonical(item)
            if event is not None:
                events.append(event)
        return events

    def upsert_mirror(self, source: CanonicalEvent) -> str:
        appointment = self._find_google_mirror(source.source_id)
        if appointment is None:
            appointment = self._ensure_app().CreateItem(OL_APPOINTMENT_ITEM)

        self._apply_source_to_appointment(appointment, source)
        self._set_user_prop(appointment, MIRROR_ORIGIN_PROP, "google")
        self._set_user_prop(appointment, MIRROR_GOOGLE_ID_PROP, source.source_id)
        appointment.Save()

        event_id = self._entry_id(appointment)
        if not event_id:
            raise RuntimeError("Outlook did not return EntryID after save.")
        return event_id

    def delete_event(self, outlook_id: str) -> None:
        namespace = self._ensure_namespace()
        try:
            item = namespace.GetItemFromID(outlook_id)
        except Exception:
            return

        try:
            item.Delete()
        except Exception:
            logger.warning("Failed to delete Outlook event id=%s", outlook_id)

    def health_check(self) -> None:
        self._ensure_calendar_folder()

    def _ensure_namespace(self) -> Any:
        if self._namespace is not None:
            return self._namespace
        if win32_client is None or pythoncom is None:
            raise RuntimeError("pywin32 is unavailable; Outlook COM requires Windows + pywin32.")

        pythoncom.CoInitialize()
        self._application = win32_client.Dispatch("Outlook.Application")
        self._namespace = self._application.GetNamespace("MAPI")
        return self._namespace

    def _ensure_app(self) -> Any:
        if self._application is not None:
            return self._application
        self._ensure_namespace()
        if self._application is None:
            raise RuntimeError("Outlook application was not initialized.")
        return self._application

    def _ensure_calendar_folder(self) -> Any:
        namespace = self._ensure_namespace()
        return namespace.GetDefaultFolder(OL_FOLDER_CALENDAR)

    def _calendar_items(self, window_start: datetime, window_end: datetime) -> Any:
        folder = self._ensure_calendar_folder()
        items = folder.Items
        items.Sort("[Start]")
        items.IncludeRecurrences = True

        start_key = self._outlook_restrict_dt(window_start)
        end_key = self._outlook_restrict_dt(window_end)
        restriction = f"[End] >= '{start_key}' AND [Start] <= '{end_key}'"
        return items.Restrict(restriction)

    def _outlook_restrict_dt(self, value: datetime) -> str:
        local_dt = value.astimezone().replace(tzinfo=None) if value.tzinfo else value
        return local_dt.strftime("%m/%d/%Y %I:%M %p")

    def _to_canonical(self, item: Any) -> CanonicalEvent | None:
        try:
            time_info = self._event_time(item)
        except Exception:
            return None

        source_id = self._event_id(item, time_info)
        if not source_id:
            return None

        mirror_origin = self._get_user_prop(item, MIRROR_ORIGIN_PROP)
        mirror_google_id = self._get_user_prop(item, MIRROR_GOOGLE_ID_PROP)

        last_modified = self._to_aware_datetime(getattr(item, "LastModificationTime", None))
        event = CanonicalEvent(
            origin="outlook",
            source_id=source_id,
            time=time_info,
            summary=str(getattr(item, "Subject", "") or ""),
            location=str(getattr(item, "Location", "") or ""),
            description=str(getattr(item, "Body", "") or ""),
            busy=getattr(item, "BusyStatus", OL_BUSY) == OL_BUSY,
            private=getattr(item, "Sensitivity", OL_PRIVATE) == OL_PRIVATE,
            last_modified=last_modified,
            mirror_origin="google" if mirror_origin == "google" else None,
            mirror_source_id=mirror_google_id,
        )
        return replace(event, fingerprint=compute_fingerprint(event))

    def _event_time(self, item: Any) -> EventTime:
        start_dt = self._to_aware_datetime(getattr(item, "Start", None))
        end_dt = self._to_aware_datetime(getattr(item, "End", None))
        if start_dt is None or end_dt is None:
            raise ValueError("Outlook item missing start/end.")

        all_day = bool(getattr(item, "AllDayEvent", False))
        if all_day:
            return EventTime(start_date=start_dt.date(), end_date=end_dt.date())
        return EventTime(start_dt=start_dt, end_dt=end_dt)

    def _event_id(self, item: Any, time_info: EventTime) -> str:
        entry_id = self._entry_id(item)
        global_id = str(getattr(item, "GlobalAppointmentID", "") or "")
        is_recurring = bool(getattr(item, "IsRecurring", False))
        if entry_id and not is_recurring:
            return entry_id

        base = global_id or entry_id
        if not base:
            return ""

        if time_info.is_all_day:
            start_key = time_info.start_date.isoformat() if time_info.start_date else ""
        else:
            start_key = time_info.start_dt.isoformat() if time_info.start_dt else ""
        return f"{base}:{start_key}" if is_recurring and start_key else base

    def _entry_id(self, item: Any) -> str:
        return str(getattr(item, "EntryID", "") or "")

    def _to_aware_datetime(self, value: Any) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is not None:
            return value
        return value.replace(tzinfo=datetime.now().astimezone().tzinfo)

    def _get_user_prop(self, item: Any, name: str) -> str:
        props = getattr(item, "UserProperties", None)
        if props is None:
            return ""

        try:
            prop = props.Find(name)
        except Exception:
            return ""
        if prop is None:
            return ""
        return str(getattr(prop, "Value", "") or "")

    def _set_user_prop(self, item: Any, name: str, value: str) -> None:
        props = item.UserProperties
        prop = props.Find(name)
        if prop is None:
            prop = props.Add(name, OL_USER_PROPERTY_TEXT)
        prop.Value = value

    def _find_google_mirror(self, google_id: str) -> Any | None:
        folder = self._ensure_calendar_folder()
        items = folder.Items
        for item in items:
            if self._get_user_prop(item, MIRROR_ORIGIN_PROP) != "google":
                continue
            if self._get_user_prop(item, MIRROR_GOOGLE_ID_PROP) == google_id:
                return item
        return None

    def _apply_source_to_appointment(self, item: Any, source: CanonicalEvent) -> None:
        item.MeetingStatus = OL_NON_MEETING
        recipients = getattr(item, "Recipients", None)
        if recipients is not None:
            for idx in range(int(recipients.Count), 0, -1):
                recipients.Remove(idx)

        item.Subject = source.summary
        item.Location = source.location
        item.Body = source.description
        item.Sensitivity = OL_PRIVATE
        item.BusyStatus = OL_BUSY

        if source.time.is_all_day:
            if source.time.start_date is None:
                raise ValueError("All-day source is missing start_date.")
            end_date = source.time.end_date or source.time.start_date
            item.AllDayEvent = True
            item.Start = datetime.combine(source.time.start_date, time.min)
            item.End = datetime.combine(end_date, time.min)
            return

        if source.time.start_dt is None or source.time.end_dt is None:
            raise ValueError("Timed source is missing start/end.")
        item.AllDayEvent = False
        item.Start = source.time.start_dt.astimezone().replace(tzinfo=None)
        item.End = source.time.end_dt.astimezone().replace(tzinfo=None)
