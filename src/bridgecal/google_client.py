from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from importlib import import_module, util
from pathlib import Path
from typing import Any

from .sync.models import CanonicalEvent, EventTime, compute_fingerprint

logger = logging.getLogger(__name__)

google_requests = (
    import_module("google.auth.transport.requests")
    if util.find_spec("google.auth.transport.requests")
    else None
)
google_credentials = (
    import_module("google.oauth2.credentials")
    if util.find_spec("google.oauth2.credentials")
    else None
)
google_oauth_flow = (
    import_module("google_auth_oauthlib.flow")
    if util.find_spec("google_auth_oauthlib.flow")
    else None
)
google_discovery = (
    import_module("googleapiclient.discovery")
    if util.find_spec("googleapiclient.discovery")
    else None
)
google_errors = (
    import_module("googleapiclient.errors") if util.find_spec("googleapiclient.errors") else None
)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
MARKER_ORIGIN_KEY = "bridgecal.origin"
MARKER_OUTLOOK_ID_KEY = "bridgecal.outlook_id"


class GoogleClient:
    def __init__(self, calendar_id: str, client_secret_path: Path, token_path: Path) -> None:
        self.calendar_id = calendar_id
        self.client_secret_path = client_secret_path
        self.token_path = token_path
        self._credentials: Any | None = None
        self._service: Any | None = None

    def list_events(self, window_start: datetime, window_end: datetime) -> Sequence[CanonicalEvent]:
        events: list[CanonicalEvent] = []
        page_token: str | None = None
        while True:
            response = (
                self._service_handle()
                .events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=self._rfc3339(window_start),
                    timeMax=self._rfc3339(window_end),
                    singleEvents=True,
                    showDeleted=False,
                    pageToken=page_token,
                )
                .execute()
            )
            items = response.get("items", [])
            for raw in items:
                event = self._to_canonical(raw)
                if event is not None:
                    events.append(event)
            page_token = response.get("nextPageToken")
            if not page_token:
                return events

    def upsert_mirror(self, source: CanonicalEvent) -> str:
        mirror_id = self._find_outlook_mirror(source.source_id)
        payload = self._mirror_payload(source)

        events_api = self._service_handle().events()
        if mirror_id:
            result = events_api.patch(
                calendarId=self.calendar_id,
                eventId=mirror_id,
                body=payload,
                sendUpdates="none",
            ).execute()
            return str(result["id"])

        result = events_api.insert(
            calendarId=self.calendar_id,
            body=payload,
            sendUpdates="none",
        ).execute()
        return str(result["id"])

    def delete_event(self, google_event_id: str) -> None:
        try:
            (
                self._service_handle()
                .events()
                .delete(
                    calendarId=self.calendar_id,
                    eventId=google_event_id,
                    sendUpdates="none",
                )
                .execute()
            )
        except Exception as exc:
            if google_errors is None or not isinstance(exc, google_errors.HttpError):
                raise
            if getattr(exc, "status_code", None) == 404:
                return
            response = getattr(exc, "resp", None)
            if response is not None and getattr(response, "status", None) == 404:
                return
            raise

    def health_check(self) -> None:
        self._service_handle().calendars().get(calendarId=self.calendar_id).execute()

    def _service_handle(self) -> Any:
        if self._service is not None:
            return self._service

        credentials = self._ensure_credentials()
        if google_discovery is None:
            raise RuntimeError("google-api-python-client is unavailable.")
        self._service = google_discovery.build(
            "calendar",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )
        return self._service

    def _ensure_credentials(self) -> Any:
        if self._credentials is not None:
            return self._credentials

        if google_credentials is None or google_oauth_flow is None or google_requests is None:
            raise RuntimeError("Google auth dependencies are unavailable.")

        creds: Any | None = None
        if self.token_path.exists():
            creds = google_credentials.Credentials.from_authorized_user_file(
                str(self.token_path), SCOPES
            )

        if creds is not None and creds.valid:
            self._credentials = creds
            return creds

        if creds is not None and creds.expired and creds.refresh_token:
            creds.refresh(google_requests.Request())
        else:
            if not self.client_secret_path.exists():
                raise RuntimeError(
                    f"Google client secret JSON not found: {self.client_secret_path}",
                )
            flow = google_oauth_flow.InstalledAppFlow.from_client_secrets_file(
                str(self.client_secret_path),
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

        self._credentials = creds
        return creds

    def _to_canonical(self, raw: dict[str, Any]) -> CanonicalEvent | None:
        if raw.get("status") == "cancelled":
            return None

        event_id = str(raw.get("id", ""))
        if not event_id:
            return None

        time_info = self._event_time(raw)
        private_props = (
            raw.get("extendedProperties", {}).get("private", {})
            if isinstance(raw.get("extendedProperties"), dict)
            else {}
        )
        marker_origin = str(private_props.get(MARKER_ORIGIN_KEY, "") or "")
        marker_outlook_id = str(private_props.get(MARKER_OUTLOOK_ID_KEY, "") or "")

        updated = self._parse_rfc3339(raw.get("updated"))
        event = CanonicalEvent(
            origin="google",
            source_id=event_id,
            time=time_info,
            summary=str(raw.get("summary", "") or ""),
            location=str(raw.get("location", "") or ""),
            description=str(raw.get("description", "") or ""),
            busy=str(raw.get("transparency", "opaque") or "opaque") != "transparent",
            private=str(raw.get("visibility", "default") or "default") == "private",
            last_modified=updated,
            mirror_origin="outlook" if marker_origin == "outlook" else None,
            mirror_source_id=marker_outlook_id,
        )
        return replace(event, fingerprint=compute_fingerprint(event))

    def _event_time(self, raw: dict[str, Any]) -> EventTime:
        start_raw = raw.get("start", {})
        end_raw = raw.get("end", {})
        if isinstance(start_raw, dict) and "date" in start_raw:
            start_date = self._parse_date(start_raw.get("date"))
            end_date = self._parse_date(end_raw.get("date"))
            return EventTime(start_date=start_date, end_date=end_date)

        start_dt = self._parse_rfc3339(
            start_raw.get("dateTime") if isinstance(start_raw, dict) else None
        )
        end_dt = self._parse_rfc3339(end_raw.get("dateTime") if isinstance(end_raw, dict) else None)
        if start_dt is None or end_dt is None:
            raise ValueError("Google event missing start/end")
        return EventTime(start_dt=start_dt, end_dt=end_dt)

    def _parse_date(self, value: Any) -> date | None:
        if not isinstance(value, str):
            return None
        return date.fromisoformat(value)

    def _parse_rfc3339(self, value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    def _rfc3339(self, value: datetime) -> str:
        normalized = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.isoformat().replace("+00:00", "Z")

    def _find_outlook_mirror(self, outlook_id: str) -> str | None:
        response = (
            self._service_handle()
            .events()
            .list(
                calendarId=self.calendar_id,
                maxResults=1,
                singleEvents=True,
                privateExtendedProperty=[
                    f"{MARKER_ORIGIN_KEY}=outlook",
                    f"{MARKER_OUTLOOK_ID_KEY}={outlook_id}",
                ],
            )
            .execute()
        )
        items = response.get("items", [])
        if not items:
            return None
        event_id = items[0].get("id")
        return str(event_id) if event_id else None

    def _mirror_payload(self, source: CanonicalEvent) -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": source.summary,
            "location": source.location,
            "description": source.description,
            "visibility": "private",
            "transparency": "opaque",
            "extendedProperties": {
                "private": {
                    MARKER_ORIGIN_KEY: "outlook",
                    MARKER_OUTLOOK_ID_KEY: source.source_id,
                }
            },
        }

        if source.time.is_all_day:
            if source.time.start_date is None:
                raise ValueError("All-day source is missing start_date.")
            end_date = source.time.end_date or (source.time.start_date + timedelta(days=1))
            body["start"] = {"date": source.time.start_date.isoformat()}
            body["end"] = {"date": end_date.isoformat()}
            return body

        if source.time.start_dt is None or source.time.end_dt is None:
            raise ValueError("Timed source is missing start/end.")
        body["start"] = {"dateTime": self._rfc3339(source.time.start_dt)}
        body["end"] = {"dateTime": self._rfc3339(source.time.end_dt)}
        return body
