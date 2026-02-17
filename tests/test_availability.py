from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

import pytest

import bridgecal.availability as availability_module
from bridgecal.availability import (
    check_availability,
    parse_natural_schedule_request,
    parse_natural_time_range,
)
from bridgecal.sync.models import CanonicalEvent, EventTime


def _timed_event(
    *,
    origin: Literal["outlook", "google"],
    source_id: str,
    summary: str,
    start: datetime,
    end: datetime,
    busy: bool = True,
) -> CanonicalEvent:
    return CanonicalEvent(
        origin=origin,
        source_id=source_id,
        time=EventTime(start_dt=start, end_dt=end),
        summary=summary,
        busy=busy,
        private=True,
    )


def _mock_lfm_response(monkeypatch: pytest.MonkeyPatch, generated_json: str) -> None:
    monkeypatch.setattr(
        availability_module,
        "_lfm_generate_local_json_response",
        lambda **_: generated_json,
    )
    monkeypatch.setattr(
        availability_module,
        "_lfm_repair_local_json_response",
        lambda **_: generated_json,
    )
    monkeypatch.setenv("BRIDGECAL_LFM25_LOCAL_MODEL", "LiquidAI/LFM2.5-1.2B-Instruct")


def test_parse_natural_time_range_japanese_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_lfm_response(
        monkeypatch,
        '{"start":"2026-02-18T10:00:00+09:00","end":"2026-02-18T17:00:00+09:00","location":""}',
    )
    now = datetime(2026, 2, 17, 8, 0, tzinfo=timezone(timedelta(hours=9)))

    result = parse_natural_time_range("明日の10時から17時", now=now, preferred_language="ja")

    assert result.start.isoformat() == "2026-02-18T10:00:00+09:00"
    assert result.end.isoformat() == "2026-02-18T17:00:00+09:00"


def test_parse_natural_time_range_english_relative(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_lfm_response(
        monkeypatch,
        '{"start":"2026-02-18T09:30:00+09:00","end":"2026-02-18T10:30:00+09:00","location":""}',
    )
    now = datetime(2026, 2, 17, 8, 0, tzinfo=timezone(timedelta(hours=9)))

    result = parse_natural_time_range(
        "tomorrow 9:30 to 10:30am",
        now=now,
        preferred_language="en",
    )

    assert result.start.isoformat() == "2026-02-18T09:30:00+09:00"
    assert result.end.isoformat() == "2026-02-18T10:30:00+09:00"


def test_parse_natural_schedule_request_with_location(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_lfm_response(
        monkeypatch,
        (
            '{"start":"2026-02-18T14:30:00+09:00",'
            '"end":"2026-02-18T15:05:00+09:00",'
            '"location":"銀座のユニクロの3階"}'
        ),
    )
    now = datetime(2026, 2, 17, 9, 0, tzinfo=timezone(timedelta(hours=9)))

    parsed = parse_natural_schedule_request(
        "明日の2時半から45分間、いややっぱり35分間だわ、銀座のユニクロの3階でね！",
        now=now,
        preferred_language="ja",
    )

    assert parsed.query_range.start.isoformat() == "2026-02-18T14:30:00+09:00"
    assert parsed.query_range.end.isoformat() == "2026-02-18T15:05:00+09:00"
    assert parsed.location == "銀座のユニクロの3階"


def test_parse_natural_schedule_request_with_thinking_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_lfm_response(
        monkeypatch,
        (
            "<think>I'll reason silently.</think>\n"
            '<answer>{"start":"2026-02-18T14:30:00+09:00",'
            '"end":"2026-02-18T15:05:00+09:00",'
            '"location":"銀座のユニクロの3階"}</answer>'
        ),
    )
    now = datetime(2026, 2, 17, 9, 0, tzinfo=timezone(timedelta(hours=9)))

    parsed = parse_natural_schedule_request(
        "明日の2時半から45分間、いややっぱり35分間だわ、銀座のユニクロの3階でね！",
        now=now,
        preferred_language="ja",
    )

    assert parsed.query_range.start.isoformat() == "2026-02-18T14:30:00+09:00"
    assert parsed.query_range.end.isoformat() == "2026-02-18T15:05:00+09:00"
    assert parsed.location == "銀座のユニクロの3階"


def test_parse_natural_time_range_can_force_thinking_with_streamed_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    streamed: list[str] = []

    def fake_generate(**kwargs: object) -> str:
        captured.update(kwargs)
        on_text_chunk = kwargs.get("on_text_chunk")
        if callable(on_text_chunk):
            on_text_chunk("<think>checking...</think>")
            on_text_chunk(
                '<answer>{"start":"2026-02-18T10:00:00+09:00",'
                '"end":"2026-02-18T11:00:00+09:00","location":"東京駅"}</answer>'
            )
        return (
            '<answer>{"start":"2026-02-18T10:00:00+09:00",'
            '"end":"2026-02-18T11:00:00+09:00","location":"東京駅"}</answer>'
        )

    monkeypatch.setattr(availability_module, "_lfm_generate_local_json_response", fake_generate)
    now = datetime(2026, 2, 17, 8, 0, tzinfo=timezone(timedelta(hours=9)))

    result = parse_natural_time_range(
        "明日の10時から11時、東京駅で",
        now=now,
        preferred_language="ja",
        model_id="Qwen/Qwen3-1.7B",
        max_new_tokens=16_384,
        force_thinking=True,
        on_model_output_chunk=streamed.append,
    )

    assert result.start.isoformat() == "2026-02-18T10:00:00+09:00"
    assert result.end.isoformat() == "2026-02-18T11:00:00+09:00"
    assert captured["model_id"] == "Qwen/Qwen3-1.7B"
    assert captured["max_new_tokens"] == 16_384
    assert captured["thinking_mode"] is True
    assert "<think>checking...</think>" in "".join(streamed)


def test_parse_natural_time_range_raises_when_lfm_output_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_lfm_response(monkeypatch, "not-json")
    now = datetime(2026, 2, 17, 8, 0, tzinfo=timezone(timedelta(hours=9)))

    with pytest.raises(RuntimeError, match="not valid JSON object text"):
        parse_natural_time_range("明日の10時から17時", now=now, preferred_language="ja")


def test_parse_natural_time_range_requires_transformers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(availability_module, "transformers", None)
    now = datetime(2026, 2, 17, 8, 0, tzinfo=timezone(timedelta(hours=9)))

    with pytest.raises(RuntimeError, match="transformers is unavailable"):
        parse_natural_time_range("明日の10時から17時", now=now, preferred_language="ja")


def test_thinking_models_do_not_force_json_prefill() -> None:
    assert (
        availability_module._should_force_assistant_json_prefill(
            model_id="LiquidAI/LFM2.5-1.2B-Thinking",
            thinking_mode=True,
        )
        is False
    )
    assert (
        availability_module._should_force_assistant_json_prefill(
            model_id="Qwen/Qwen3-1.7B",
            thinking_mode=True,
        )
        is False
    )


def test_check_availability_dedupes_same_busy_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_lfm_response(
        monkeypatch,
        '{"start":"2026-02-18T10:00:00+00:00","end":"2026-02-18T11:00:00+00:00","location":""}',
    )
    query_range = parse_natural_time_range(
        "2026-02-18 10:00-11:00",
        now=datetime(2026, 2, 17, 0, 0, tzinfo=UTC),
        preferred_language="en",
    )
    event_start = datetime(2026, 2, 18, 10, 15, tzinfo=UTC)
    event_end = datetime(2026, 2, 18, 10, 45, tzinfo=UTC)

    outlook_events = [
        _timed_event(
            origin="outlook",
            source_id="o-1",
            summary="Board meeting",
            start=event_start,
            end=event_end,
        )
    ]
    google_events = [
        _timed_event(
            origin="google",
            source_id="g-1",
            summary="Board meeting",
            start=event_start,
            end=event_end,
        ),
        _timed_event(
            origin="google",
            source_id="g-2",
            summary="Optional block",
            start=event_start,
            end=event_end,
            busy=False,
        ),
    ]

    result = check_availability(
        query_text="2026-02-18 10:00-11:00",
        query_range=query_range,
        outlook_events=outlook_events,
        google_events=google_events,
    )

    assert result.available is False
    assert len(result.conflicts) == 1
    assert result.conflicts[0].summary == "Board meeting"
