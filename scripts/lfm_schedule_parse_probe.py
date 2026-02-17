from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bridgecal.availability import ParsedScheduleRequest, parse_natural_schedule_request

JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class ExpectedResult:
    start: datetime
    end: datetime
    location: str


@dataclass(frozen=True)
class ParseCase:
    case_id: str
    language: str
    text: str
    expected_builder: Callable[[datetime], ExpectedResult]


def _at(base: datetime, *, days: int, hour: int, minute: int) -> datetime:
    return (base + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _build_cases() -> list[ParseCase]:
    return [
        ParseCase(
            case_id="ja-1",
            language="ja",
            text="明日の2時半から45分間、いややっぱり35分間だわ、銀座のユニクロの3階でね！",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=1, hour=14, minute=30),
                end=_at(now, days=1, hour=15, minute=5),
                location="銀座のユニクロの3階",
            ),
        ),
        ParseCase(
            case_id="ja-2",
            language="ja",
            text="明日の夜11時50分から2時間、訂正で1時間20分、新橋駅SL広場で。",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=1, hour=23, minute=50),
                end=_at(now, days=2, hour=1, minute=10),
                location="新橋駅SL広場",
            ),
        ),
        ParseCase(
            case_id="ja-3",
            language="ja",
            text="明後日の朝9時から3時間…じゃなくて開始9時20分、2時間15分。大手町タワー27階。",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=2, hour=9, minute=20),
                end=_at(now, days=2, hour=11, minute=35),
                location="大手町タワー27階",
            ),
        ),
        ParseCase(
            case_id="ja-4",
            language="ja",
            text="3日後の13時から16時、いや15時半まで。渋谷ヒカリエ8Fで。",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=3, hour=13, minute=0),
                end=_at(now, days=3, hour=15, minute=30),
                location="渋谷ヒカリエ8F",
            ),
        ),
        ParseCase(
            case_id="ja-5",
            language="ja",
            text="4日後の正午から75分、やっぱり60分。東京駅丸の内北口。",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=4, hour=12, minute=0),
                end=_at(now, days=4, hour=13, minute=0),
                location="東京駅丸の内北口",
            ),
        ),
        ParseCase(
            case_id="ja-6",
            language="ja",
            text="5日後の23時40分から50分間、場所は品川駅港南口。",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=5, hour=23, minute=40),
                end=_at(now, days=6, hour=0, minute=30),
                location="品川駅港南口",
            ),
        ),
        ParseCase(
            case_id="en-1",
            language="en",
            text="Tomorrow from 2:30 PM for 45 minutes, no make it 35 minutes, at UNIQLO Ginza 3F.",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=1, hour=14, minute=30),
                end=_at(now, days=1, hour=15, minute=5),
                location="UNIQLO Ginza 3F",
            ),
        ),
        ParseCase(
            case_id="en-2",
            language="en",
            text="Tomorrow at 11:50 PM for 2 hours, correction: 80 minutes, at Shimbashi SL Square.",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=1, hour=23, minute=50),
                end=_at(now, days=2, hour=1, minute=10),
                location="Shimbashi SL Square",
            ),
        ),
        ParseCase(
            case_id="en-3",
            language="en",
            text="Day after tomorrow from 9:00 AM, actually start 9:20 AM, for 2 hours 15 minutes, at Otemachi Tower 27F.",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=2, hour=9, minute=20),
                end=_at(now, days=2, hour=11, minute=35),
                location="Otemachi Tower 27F",
            ),
        ),
        ParseCase(
            case_id="en-4",
            language="en",
            text="In 3 days from 1 PM to 4 PM, no end at 3:30 PM, at Shibuya Hikarie 8F.",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=3, hour=13, minute=0),
                end=_at(now, days=3, hour=15, minute=30),
                location="Shibuya Hikarie 8F",
            ),
        ),
        ParseCase(
            case_id="en-5",
            language="en",
            text="In 4 days at noon for 75 minutes, actually 60, at Tokyo Station Marunouchi North Exit.",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=4, hour=12, minute=0),
                end=_at(now, days=4, hour=13, minute=0),
                location="Tokyo Station Marunouchi North Exit",
            ),
        ),
        ParseCase(
            case_id="en-6",
            language="en",
            text="In 5 days starting 11:40 PM for 50 minutes at Shinagawa Station Konan Exit.",
            expected_builder=lambda now: ExpectedResult(
                start=_at(now, days=5, hour=23, minute=40),
                end=_at(now, days=6, hour=0, minute=30),
                location="Shinagawa Station Konan Exit",
            ),
        ),
    ]


def _format(parsed: ParsedScheduleRequest) -> str:
    return (
        f"start={parsed.query_range.start.isoformat()} "
        f"end={parsed.query_range.end.isoformat()} "
        f"location={parsed.location}"
    )


def main() -> int:
    now_jst = datetime.now(JST).replace(second=0, microsecond=0)
    print(f"reference_time={now_jst.isoformat()}")

    cases = _build_cases()
    passed = 0
    for case in cases:
        expected = case.expected_builder(now_jst)
        try:
            parsed = parse_natural_schedule_request(
                case.text,
                now=now_jst,
                preferred_language=case.language,
            )
        except Exception as exc:  # pragma: no cover - manual probe
            cause = exc.__cause__
            print(f"[FAIL] {case.case_id}: exception={exc}")
            if cause is not None:
                print(f"  cause: {type(cause).__name__}: {cause}")
                traceback.print_exception(cause)
            continue

        start_ok = parsed.query_range.start == expected.start
        end_ok = parsed.query_range.end == expected.end
        location_ok = parsed.location == expected.location
        ok = start_ok and end_ok and location_ok
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1

        print(f"[{status}] {case.case_id} ({case.language})")
        print(f"  input: {case.text}")
        print(
            "  expected: "
            f"start={expected.start.isoformat()} "
            f"end={expected.end.isoformat()} "
            f"location={expected.location}"
        )
        print(f"  actual:   {_format(parsed)}")

    total = len(cases)
    print(f"summary: passed={passed}/{total} failed={total - passed}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
