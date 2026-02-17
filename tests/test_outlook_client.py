from datetime import UTC, datetime
from types import SimpleNamespace

from bridgecal.outlook_client import OutlookClient, _extract_executable_path, _is_outlook_busy_error
from bridgecal.sync.models import CanonicalEvent, EventTime


def test_extract_executable_path_from_quoted_command() -> None:
    command = '"C:\\Program Files\\Microsoft Office\\Root\\Office16\\OUTLOOK.EXE" /embedding'
    assert (
        _extract_executable_path(command)
        == "C:\\Program Files\\Microsoft Office\\Root\\Office16\\OUTLOOK.EXE"
    )


def test_extract_executable_path_from_unquoted_command() -> None:
    command = "C:\\Tools\\OUTLOOK.EXE /recycle"
    assert _extract_executable_path(command) == "C:\\Tools\\OUTLOOK.EXE"


def test_extract_executable_path_returns_none_for_empty_text() -> None:
    assert _extract_executable_path("   ") is None


def test_extract_executable_path_returns_none_for_invalid_quoted_text() -> None:
    assert _extract_executable_path('"C:\\Program Files\\OUTLOOK.EXE') is None


def test_is_outlook_busy_error_with_rejected_by_callee_text() -> None:
    assert _is_outlook_busy_error(RuntimeError("Call was rejected by callee.")) is True


def test_is_outlook_busy_error_with_hresult_code() -> None:
    assert _is_outlook_busy_error(Exception(-2147418111, "busy")) is True


def test_is_outlook_busy_error_with_other_error() -> None:
    assert _is_outlook_busy_error(RuntimeError("different failure")) is False


def test_event_time_uses_startutc_for_timed_events() -> None:
    item = SimpleNamespace(
        AllDayEvent=False,
        Start=datetime(2026, 2, 16, 17, 0, tzinfo=UTC),
        End=datetime(2026, 2, 16, 18, 0, tzinfo=UTC),
        StartUTC=datetime(2026, 2, 16, 8, 0, tzinfo=UTC),
        EndUTC=datetime(2026, 2, 16, 9, 0, tzinfo=UTC),
    )

    event_time = OutlookClient()._event_time(item)
    assert event_time.start_dt == datetime(2026, 2, 16, 8, 0, tzinfo=UTC)
    assert event_time.end_dt == datetime(2026, 2, 16, 9, 0, tzinfo=UTC)


def test_event_time_uses_wall_dates_for_all_day_events() -> None:
    item = SimpleNamespace(
        AllDayEvent=True,
        Start=datetime(2026, 2, 16, 0, 0, tzinfo=UTC),
        End=datetime(2026, 2, 17, 0, 0, tzinfo=UTC),
        StartUTC=datetime(2026, 2, 15, 15, 0, tzinfo=UTC),
        EndUTC=datetime(2026, 2, 16, 15, 0, tzinfo=UTC),
    )

    event_time = OutlookClient()._event_time(item)
    assert event_time.start_date == datetime(2026, 2, 16, 0, 0).date()
    assert event_time.end_date == datetime(2026, 2, 17, 0, 0).date()


def test_apply_source_to_appointment_sets_startutc_for_timed_events() -> None:
    class _Recipients:
        Count = 0

        def Remove(self, idx: int) -> None:
            raise AssertionError(f"unexpected recipient removal: {idx}")

    item = SimpleNamespace(
        MeetingStatus=None,
        Recipients=_Recipients(),
        Subject="",
        Location="",
        Body="",
        Sensitivity=None,
        BusyStatus=None,
        AllDayEvent=None,
        StartUTC=None,
        EndUTC=None,
    )
    source = CanonicalEvent(
        origin="google",
        source_id="g1",
        time=EventTime(
            start_dt=datetime(2026, 2, 18, 9, 30, tzinfo=UTC).astimezone(),
            end_dt=datetime(2026, 2, 18, 10, 30, tzinfo=UTC).astimezone(),
        ),
        summary="s",
        location="l",
        description="d",
    )

    OutlookClient()._apply_source_to_appointment(item, source)

    assert item.AllDayEvent is False
    assert item.StartUTC == source.time.start_dt.astimezone(UTC)
    assert item.EndUTC == source.time.end_dt.astimezone(UTC)
