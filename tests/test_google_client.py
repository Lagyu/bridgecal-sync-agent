from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import bridgecal.google_client as google_client_module
from bridgecal.google_client import (
    GoogleClient,
    _load_json_object,
    _validate_desktop_client_secret_config,
)


def test_load_json_object_rejects_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "google_client_secret.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"installed": {}}')

    with pytest.raises(RuntimeError, match="UTF-8 without BOM"):
        _load_json_object(path, label="Google client secret JSON")


def test_load_json_object_requires_object_top_level(tmp_path: Path) -> None:
    path = tmp_path / "google_client_secret.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="must be a JSON object"):
        _load_json_object(path, label="Google client secret JSON")


def test_load_json_object_accepts_utf8_without_bom(tmp_path: Path) -> None:
    path = tmp_path / "google_client_secret.json"
    path.write_text('{"installed": {}}', encoding="utf-8")

    payload = _load_json_object(path, label="Google client secret JSON")

    assert payload == {"installed": {}}


def test_validate_desktop_client_secret_config_requires_fields(tmp_path: Path) -> None:
    payload = {
        "installed": {
            "client_id": "id",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    with pytest.raises(RuntimeError, match="missing required field"):
        _validate_desktop_client_secret_config(payload, tmp_path / "google_client_secret.json")


def test_validate_desktop_client_secret_config_requires_localhost_redirect(tmp_path: Path) -> None:
    payload = {
        "installed": {
            "client_id": "id",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["https://example.com/callback"],
        }
    }

    with pytest.raises(RuntimeError, match="localhost/127.0.0.1"):
        _validate_desktop_client_secret_config(payload, tmp_path / "google_client_secret.json")


def test_google_client_defaults_to_insecure_tls_skip_verify() -> None:
    client = GoogleClient(
        calendar_id="primary",
        client_secret_path=Path("secret.json"),
        token_path=Path("token.json"),
    )

    assert client.insecure_tls_skip_verify is True


def test_google_client_disables_oauth_session_verify_in_insecure_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCreds:
        def __init__(self) -> None:
            self.valid = True

        def to_json(self) -> str:
            return json.dumps({"token": "x"})

    class FakeFlow:
        def __init__(self) -> None:
            self.oauth2session = SimpleNamespace(verify=True)
            self.ran = False

        def run_local_server(self, port: int = 0) -> FakeCreds:
            assert port == 0
            self.ran = True
            return FakeCreds()

    fake_flow = FakeFlow()

    class FakeInstalledAppFlow:
        @staticmethod
        def from_client_config(client_config: dict[str, Any], scopes: list[str]) -> FakeFlow:
            assert client_config["installed"]["client_id"] == "id"
            assert scopes == ["https://www.googleapis.com/auth/calendar"]
            return fake_flow

    fake_google_oauth_flow = SimpleNamespace(InstalledAppFlow=FakeInstalledAppFlow)
    fake_google_credentials = SimpleNamespace(Credentials=SimpleNamespace())
    fake_google_requests = object()
    warnings_called = {"value": False}

    def fake_disable_warnings(_: Any) -> None:
        warnings_called["value"] = True

    fake_urllib3 = SimpleNamespace(
        exceptions=SimpleNamespace(InsecureRequestWarning=RuntimeWarning),
        disable_warnings=fake_disable_warnings,
    )

    monkeypatch.setattr(google_client_module, "google_oauth_flow", fake_google_oauth_flow)
    monkeypatch.setattr(google_client_module, "google_credentials", fake_google_credentials)
    monkeypatch.setattr(google_client_module, "google_requests", fake_google_requests)
    monkeypatch.setattr(google_client_module, "urllib3", fake_urllib3)

    client_secret_path = tmp_path / "google_client_secret.json"
    client_secret_path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "id",
                    "client_secret": "secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )

    token_path = tmp_path / "google_token.json"
    client = GoogleClient(
        calendar_id="primary",
        client_secret_path=client_secret_path,
        token_path=token_path,
        insecure_tls_skip_verify=True,
    )

    client._ensure_credentials()

    assert fake_flow.oauth2session.verify is False
    assert fake_flow.ran is True
    assert warnings_called["value"] is True


def test_google_event_time_uses_timezone_field_when_offset_missing() -> None:
    client = GoogleClient(
        calendar_id="primary",
        client_secret_path=Path("secret.json"),
        token_path=Path("token.json"),
    )

    event_time = client._event_time(
        {
            "start": {"dateTime": "2026-02-18T09:30:00", "timeZone": "Asia/Tokyo"},
            "end": {"dateTime": "2026-02-18T10:30:00", "timeZone": "Asia/Tokyo"},
        }
    )

    assert event_time.start_dt is not None
    assert event_time.end_dt is not None
    assert event_time.start_dt.isoformat() == "2026-02-18T09:30:00+09:00"
    assert event_time.end_dt.isoformat() == "2026-02-18T10:30:00+09:00"
