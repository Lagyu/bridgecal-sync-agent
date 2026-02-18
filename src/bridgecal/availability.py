from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from importlib import import_module, util
from threading import Lock, Thread
from typing import Any, Literal

from .sync.models import CanonicalEvent

logger = logging.getLogger(__name__)

AvailabilityOrigin = Literal["outlook", "google"]


def _optional_import(module_name: str) -> Any | None:
    if util.find_spec(module_name) is None:
        return None
    try:
        return import_module(module_name)
    except Exception:
        return None


transformers = _optional_import("transformers")
torch = _optional_import("torch")

_pipeline_lock = Lock()
_pipeline_cache: dict[str, Any] = {}
_pipeline_failed_models: set[str] = set()


@dataclass(frozen=True)
class QueryTimeRange:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class ParsedScheduleRequest:
    query_range: QueryTimeRange
    location: str = ""


@dataclass(frozen=True)
class AvailabilityConflict:
    origin: AvailabilityOrigin
    source_id: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool


@dataclass(frozen=True)
class AvailabilityResult:
    query_text: str
    query_range: QueryTimeRange
    conflicts: list[AvailabilityConflict]

    @property
    def available(self) -> bool:
        return not self.conflicts


def parse_natural_schedule_request(
    text: str,
    *,
    now: datetime | None = None,
    preferred_language: str = "ja",
    model_id: str | None = None,
    max_new_tokens: int | None = None,
    force_thinking: bool = False,
    on_model_output_chunk: Callable[[str], None] | None = None,
) -> ParsedScheduleRequest:
    normalized = _normalize_text(text)
    if not normalized:
        raise ValueError("Input is empty.")

    base_now = now or datetime.now().astimezone()
    local_tz = _local_timezone(base_now)
    selected_model_id = model_id.strip() if model_id and model_id.strip() else _read_lfm_model_id()
    requested_max_new_tokens = (
        _read_lfm_max_new_tokens()
        if max_new_tokens is None
        else _normalize_max_new_tokens(max_new_tokens)
    )
    effective_max_new_tokens = _effective_max_new_tokens(
        model_id=selected_model_id,
        requested=requested_max_new_tokens,
    )
    thinking_mode = force_thinking or _uses_reasoning_output_mode(selected_model_id)
    base_seed = _read_lfm_seed()

    generated = _lfm_generate_local_json_response(
        query_text=normalized,
        preferred_language=preferred_language,
        reference_time=base_now,
        max_new_tokens=effective_max_new_tokens,
        seed=base_seed,
        model_id=selected_model_id,
        thinking_mode=thinking_mode,
        on_text_chunk=on_model_output_chunk,
    )
    payload = _json_object_from_text(generated)
    return _build_schedule_request_from_payload(payload, fallback_tz=local_tz)


def parse_natural_time_range(
    text: str,
    *,
    now: datetime | None = None,
    preferred_language: str = "ja",
    model_id: str | None = None,
    max_new_tokens: int | None = None,
    force_thinking: bool = False,
    on_model_output_chunk: Callable[[str], None] | None = None,
) -> QueryTimeRange:
    parsed = parse_natural_schedule_request(
        text=text,
        now=now,
        preferred_language=preferred_language,
        model_id=model_id,
        max_new_tokens=max_new_tokens,
        force_thinking=force_thinking,
        on_model_output_chunk=on_model_output_chunk,
    )
    return parsed.query_range


def check_availability(
    *,
    query_text: str,
    query_range: QueryTimeRange,
    outlook_events: list[CanonicalEvent],
    google_events: list[CanonicalEvent],
) -> AvailabilityResult:
    window_start_utc = _to_utc(query_range.start)
    window_end_utc = _to_utc(query_range.end)

    conflicts: list[AvailabilityConflict] = []
    seen: set[tuple[str, str, str]] = set()
    event_sets: tuple[tuple[AvailabilityOrigin, list[CanonicalEvent]], ...] = (
        ("outlook", outlook_events),
        ("google", google_events),
    )
    for origin, events in event_sets:
        for event in events:
            if not event.busy:
                continue
            event_start_utc, event_end_utc, all_day = _event_range_utc(event)
            if not _overlaps(
                start_a=event_start_utc,
                end_a=event_end_utc,
                start_b=window_start_utc,
                end_b=window_end_utc,
            ):
                continue

            event_start_local = event_start_utc.astimezone(query_range.start.tzinfo)
            event_end_local = event_end_utc.astimezone(query_range.start.tzinfo)
            dedupe_key = (
                event_start_local.isoformat(),
                event_end_local.isoformat(),
                (event.summary or "").strip().casefold(),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            conflicts.append(
                AvailabilityConflict(
                    origin=origin,
                    source_id=event.source_id,
                    summary=event.summary,
                    start=event_start_local,
                    end=event_end_local,
                    all_day=all_day,
                )
            )

    conflicts.sort(key=lambda conflict: conflict.start)
    return AvailabilityResult(
        query_text=query_text,
        query_range=query_range,
        conflicts=conflicts,
    )


def _lfm_generate_local_json_response(
    *,
    query_text: str,
    preferred_language: str,
    reference_time: datetime,
    max_new_tokens: int,
    seed: int,
    model_id: str,
    thinking_mode: bool | None = None,
    on_text_chunk: Callable[[str], None] | None = None,
) -> str:
    pipe = _lfm_transformers_pipeline(model_id=model_id)
    effective_thinking_mode = (
        _uses_reasoning_output_mode(model_id) if thinking_mode is None else thinking_mode
    )
    messages = [
        {
            "role": "system",
            "content": _lfm_system_prompt(
                reference_time=reference_time,
                thinking_mode=effective_thinking_mode,
            ),
        },
        {
            "role": "user",
            "content": _lfm_input_text(
                query_text=query_text,
                preferred_language=preferred_language,
                reference_time=reference_time,
            ),
        },
    ]
    assistant_prefill = ""
    if _should_force_assistant_json_prefill(
        model_id=model_id,
        thinking_mode=effective_thinking_mode,
    ):
        messages.append({"role": "assistant", "content": "{"})
        prompt = _render_chat_prompt(
            pipe=pipe,
            model_id=model_id,
            thinking_mode=effective_thinking_mode,
            messages=messages,
            add_generation_prompt=False,
            continue_final_message=True,
        )
        assistant_prefill = "{"
    else:
        prompt = _render_chat_prompt(
            pipe=pipe,
            model_id=model_id,
            thinking_mode=effective_thinking_mode,
            messages=messages,
            add_generation_prompt=True,
        )
    return _run_generation(
        pipe=pipe,
        prompt=prompt,
        max_new_tokens=max_new_tokens,
        seed=seed,
        model_id=model_id,
        assistant_prefill=assistant_prefill,
        on_text_chunk=on_text_chunk,
    )


def _lfm_repair_local_json_response(
    *,
    query_text: str,
    preferred_language: str,
    reference_time: datetime,
    invalid_output: str,
    validation_error: str,
    max_new_tokens: int,
    seed: int,
    model_id: str,
) -> str:
    pipe = _lfm_transformers_pipeline(model_id=model_id)
    thinking_mode = _uses_reasoning_output_mode(model_id)
    messages = [
        {
            "role": "system",
            "content": _lfm_repair_system_prompt(
                reference_time=reference_time,
                thinking_mode=thinking_mode,
            ),
        },
        {
            "role": "user",
            "content": _lfm_repair_input_text(
                query_text=query_text,
                preferred_language=preferred_language,
                reference_time=reference_time,
                invalid_output=invalid_output,
                validation_error=validation_error,
            ),
        },
    ]
    assistant_prefill = ""
    if _should_force_assistant_json_prefill(model_id=model_id, thinking_mode=thinking_mode):
        messages.append({"role": "assistant", "content": "{"})
        prompt = _render_chat_prompt(
            pipe=pipe,
            model_id=model_id,
            thinking_mode=thinking_mode,
            messages=messages,
            add_generation_prompt=False,
            continue_final_message=True,
        )
        assistant_prefill = "{"
    else:
        prompt = _render_chat_prompt(
            pipe=pipe,
            model_id=model_id,
            thinking_mode=thinking_mode,
            messages=messages,
            add_generation_prompt=True,
        )
    return _run_generation(
        pipe=pipe,
        prompt=prompt,
        max_new_tokens=max_new_tokens,
        seed=seed,
        model_id=model_id,
        assistant_prefill=assistant_prefill,
    )


def _run_generation(
    *,
    pipe: Any,
    prompt: str,
    max_new_tokens: int,
    seed: int,
    model_id: str,
    assistant_prefill: str,
    on_text_chunk: Callable[[str], None] | None = None,
) -> str:
    if torch is not None:
        manual_seed = getattr(torch, "manual_seed", None)
        if callable(manual_seed):
            manual_seed(seed)

    generation_kwargs = _generation_kwargs(
        model_id=model_id,
        max_new_tokens=max_new_tokens,
    )
    tokenizer = getattr(pipe, "tokenizer", None)
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if isinstance(eos_token_id, int):
        generation_kwargs["eos_token_id"] = eos_token_id
        generation_kwargs["pad_token_id"] = eos_token_id

    streamed_text = _run_generation_with_streamer(
        pipe=pipe,
        prompt=prompt,
        generation_kwargs=generation_kwargs,
        on_text_chunk=on_text_chunk,
    )
    if streamed_text is not None:
        text = streamed_text
        if assistant_prefill and not text.lstrip().startswith(assistant_prefill):
            text = assistant_prefill + text
            if on_text_chunk is not None:
                on_text_chunk(assistant_prefill)
        if not text.strip():
            raise RuntimeError("LFM local generation returned empty text.")
        return text

    outputs: Any
    try:
        outputs = pipe(prompt, return_full_text=False, **generation_kwargs)
    except TypeError:
        outputs = pipe(prompt, **generation_kwargs)
    except Exception as exc:
        raise RuntimeError("LFM local generation via transformers failed.") from exc

    text = _extract_transformers_generated_text(outputs)
    if assistant_prefill and not text.lstrip().startswith(assistant_prefill):
        text = assistant_prefill + text
    if on_text_chunk is not None:
        on_text_chunk(text)
    if not text.strip():
        raise RuntimeError("LFM local generation returned empty text.")
    return text


def _run_generation_with_streamer(
    *,
    pipe: Any,
    prompt: str,
    generation_kwargs: dict[str, Any],
    on_text_chunk: Callable[[str], None] | None,
) -> str | None:
    if on_text_chunk is None or transformers is None:
        return None

    streamer_cls = getattr(transformers, "TextIteratorStreamer", None)
    tokenizer = getattr(pipe, "tokenizer", None)
    if streamer_cls is None or tokenizer is None:
        return None

    try:
        streamer = streamer_cls(tokenizer, skip_prompt=True, skip_special_tokens=False)
    except Exception:
        return None

    output_holder: dict[str, Any] = {}
    failure_holder: dict[str, Exception] = {}

    def run_pipe() -> None:
        try:
            output_holder["value"] = pipe(
                prompt,
                return_full_text=False,
                streamer=streamer,
                **generation_kwargs,
            )
        except TypeError:
            try:
                output_holder["value"] = pipe(prompt, streamer=streamer, **generation_kwargs)
            except Exception as exc:  # pragma: no cover - defensive guard
                failure_holder["error"] = exc
        except Exception as exc:  # pragma: no cover - defensive guard
            failure_holder["error"] = exc

    generation_thread = Thread(target=run_pipe, daemon=True)
    generation_thread.start()

    chunks: list[str] = []
    try:
        for chunk in streamer:
            if not isinstance(chunk, str) or not chunk:
                continue
            chunks.append(chunk)
            on_text_chunk(chunk)
    except Exception:
        return None
    finally:
        generation_thread.join()

    error = failure_holder.get("error")
    if error is not None:
        raise RuntimeError("LFM local generation via transformers failed.") from error

    text = "".join(chunks)
    if text.strip():
        return text

    output = output_holder.get("value")
    if output is None:
        return None
    extracted = _extract_transformers_generated_text(output)
    if extracted.strip():
        on_text_chunk(extracted)
        return extracted
    return None


def _generation_kwargs(*, model_id: str, max_new_tokens: int) -> dict[str, Any]:
    if _is_qwen3_model(model_id):
        return {
            "max_new_tokens": max_new_tokens,
            "do_sample": True,
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 20,
        }

    if _is_lfm_thinking_model(model_id):
        # LFM thinking variants perform better when sampling is enabled.
        return {
            "max_new_tokens": max_new_tokens,
            "do_sample": True,
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 40,
        }
    return {
        "max_new_tokens": max_new_tokens,
        "do_sample": False,
        "temperature": 0.0,
        "top_p": 1.0,
    }


def _extract_transformers_generated_text(outputs: Any) -> str:
    if isinstance(outputs, list) and outputs:
        first = outputs[0]
        if isinstance(first, dict):
            generated = first.get("generated_text") or first.get("text")
            if isinstance(generated, str):
                return generated
            if isinstance(generated, list) and generated:
                last = generated[-1]
                if isinstance(last, dict):
                    content = last.get("content")
                    if isinstance(content, str):
                        return content
        if isinstance(first, str):
            return first
    if isinstance(outputs, dict):
        generated = outputs.get("generated_text") or outputs.get("text")
        if isinstance(generated, str):
            return generated
    raise RuntimeError("LFM local generation returned unexpected output type.")


def _lfm_transformers_pipeline(*, model_id: str) -> Any:
    if transformers is None:
        raise RuntimeError("transformers is unavailable for local LFM parsing.")

    with _pipeline_lock:
        cached = _pipeline_cache.get(model_id)
        if cached is not None:
            return cached
        if model_id in _pipeline_failed_models:
            raise RuntimeError(f"LFM local model initialization previously failed: {model_id}")

        pipeline_builder = getattr(transformers, "pipeline", None)
        if pipeline_builder is None:
            raise RuntimeError("transformers.pipeline is unavailable.")

        allow_remote_code = _read_lfm_allow_remote_code()
        pipeline_kwargs: dict[str, Any] = {
            "task": "text-generation",
            "model": model_id,
            "tokenizer": model_id,
            "trust_remote_code": allow_remote_code,
        }
        model_kwargs: dict[str, Any] = {}
        dtype_name = _read_lfm_torch_dtype()
        if dtype_name and torch is not None:
            dtype = getattr(torch, dtype_name, None)
            if dtype is not None:
                model_kwargs["dtype"] = dtype
        if model_kwargs:
            pipeline_kwargs["model_kwargs"] = model_kwargs

        device_mode = _read_lfm_device_mode()
        if device_mode == "auto":
            pipeline_kwargs["device_map"] = "auto"
        else:
            pipeline_kwargs["device"] = -1

        try:
            pipe = pipeline_builder(**pipeline_kwargs)
        except Exception as exc:
            _pipeline_failed_models.add(model_id)
            if not allow_remote_code:
                raise RuntimeError(
                    "Failed to initialize local transformers model: "
                    f"{model_id}. If this model requires remote code, set "
                    "BRIDGECAL_LFM25_ALLOW_REMOTE_CODE=true explicitly."
                ) from exc
            raise RuntimeError(
                f"Failed to initialize local transformers model: {model_id}"
            ) from exc

        generation_config = getattr(getattr(pipe, "model", None), "generation_config", None)
        if generation_config is not None and getattr(generation_config, "max_length", None) == 20:
            with suppress(Exception):
                generation_config.max_length = None

        _pipeline_cache[model_id] = pipe
        _pipeline_failed_models.discard(model_id)
        return pipe


def _render_chat_prompt(
    *,
    pipe: Any,
    model_id: str,
    thinking_mode: bool,
    messages: list[dict[str, str]],
    add_generation_prompt: bool,
    continue_final_message: bool = False,
) -> str:
    tokenizer = getattr(pipe, "tokenizer", None)
    apply_chat_template = getattr(tokenizer, "apply_chat_template", None)
    template_kwargs = _chat_template_kwargs(
        model_id=model_id,
        thinking_mode=thinking_mode,
    )
    if callable(apply_chat_template):
        try:
            rendered = apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=add_generation_prompt,
                continue_final_message=continue_final_message,
                **template_kwargs,
            )
            if isinstance(rendered, str) and rendered.strip():
                return rendered
        except TypeError:
            try:
                rendered = apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=add_generation_prompt,
                    **template_kwargs,
                )
                if isinstance(rendered, str) and rendered.strip():
                    return rendered
            except Exception:
                pass
        except Exception:
            pass

    # Conservative fallback if chat template is unavailable.
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "user").upper()
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    if add_generation_prompt:
        lines.append("ASSISTANT:")
    return "\n".join(lines)


def _lfm_system_prompt(*, reference_time: datetime, thinking_mode: bool) -> str:
    reference_iso = reference_time.isoformat()
    reference_date = reference_time.date().isoformat()
    offset = reference_time.strftime("%z")
    tz_offset = f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"
    output_format = (
        "Output exactly one JSON object with keys start, end, location. No prose or markdown."
    )
    if thinking_mode:
        output_format = (
            "Always output exactly one <think>...</think> block first, then "
            'one <answer>{"start":"...","end":"...","location":"..."}</answer> block.'
        )
    return (
        "You are a strict parser for calendar requests.\n"
        "Return one structured result that matches the provided schema.\n"
        "Reference clock (from local machine):\n"
        f"- current_local_datetime: {reference_iso}\n"
        f"- current_local_date: {reference_date}\n"
        f"- current_timezone_offset: {tz_offset}\n"
        "Rules:\n"
        "1) start and end must be valid ISO-8601 datetimes with timezone offsets.\n"
        "2) Use the timezone offset from reference_time for relative phrases.\n"
        "3) If the request includes corrections (e.g. 'no', 'actually', '訂正', 'いや', "
        "'やっぱり'), the latest correction overrides earlier conflicting values.\n"
        "4) Normalize time arithmetic: never emit invalid clock values like hour 24+.\n"
        "5) If time is ambiguous in Japanese (e.g. '2時半') and there is no explicit 朝/午前/深夜, "
        "assume daytime (14:30).\n"
        "6) location must be the shortest phrase from input; do not append inferred city/country.\n"
        "7) When multiple durations/times appear, always apply the latest correction to compute end.\n"
        "8) location must be copied from the query text verbatim (or empty string if absent).\n"
        f"9) {output_format}"
    )


def _lfm_repair_system_prompt(*, reference_time: datetime, thinking_mode: bool) -> str:
    reference_iso = reference_time.isoformat()
    reference_date = reference_time.date().isoformat()
    offset = reference_time.strftime("%z")
    tz_offset = f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"
    output_format = "Return one JSON object with keys start, end, location."
    if thinking_mode:
        output_format = (
            "Always output exactly one <think>...</think> block first, then "
            'one <answer>{"start":"...","end":"...","location":"..."}</answer> block.'
        )
    return (
        "You repair invalid calendar parser JSON outputs.\n"
        f"{output_format}\n"
        "Reference clock (from local machine):\n"
        f"- current_local_datetime: {reference_iso}\n"
        f"- current_local_date: {reference_date}\n"
        f"- current_timezone_offset: {tz_offset}\n"
        "Fix all validation errors:\n"
        "- start/end must be valid ISO-8601 datetime strings with timezone offsets.\n"
        "- never use hour 24+.\n"
        "- if any hour is 24 or greater, roll over to next day and normalize to 00-23.\n"
        "- keep the latest correction when the query revises duration or time.\n"
        "- recompute end from start + latest duration when duration is provided.\n"
        "- location must be copied from query text; do not translate or infer city/country.\n"
        "Do not return prose or markdown."
    )


def _lfm_input_text(
    *,
    query_text: str,
    preferred_language: str,
    reference_time: datetime,
) -> str:
    return (
        "task: parse_calendar_time_range\n"
        f"language: {preferred_language}\n"
        f"reference_time: {reference_time.isoformat()}\n"
        f"query: {query_text}"
    )


def _lfm_repair_input_text(
    *,
    query_text: str,
    preferred_language: str,
    reference_time: datetime,
    invalid_output: str,
    validation_error: str,
) -> str:
    return (
        "task: repair_calendar_time_range_json\n"
        f"language: {preferred_language}\n"
        f"reference_time: {reference_time.isoformat()}\n"
        f"query: {query_text}\n"
        f"validation_error: {validation_error}\n"
        "invalid_output:\n"
        f"{invalid_output}"
    )


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    for candidate in _json_candidates_from_generation(text):
        parsed = _try_parse_json_object(candidate)
        if parsed is not None:
            return parsed

        scanned = _scan_first_json_object(candidate)
        if scanned is not None:
            return scanned
    return None


def _json_candidates_from_generation(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []

    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = value.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    think_end_matches = list(re.finditer(r"</think>", stripped, flags=re.IGNORECASE))
    if think_end_matches:
        # In reasoning mode, the final answer is expected after </think>.
        add(stripped[think_end_matches[-1].end() :])

    answer_content_matches = list(
        re.finditer(r"<answer>(.*?)</answer>", stripped, flags=re.IGNORECASE | re.DOTALL)
    )
    if answer_content_matches:
        add(answer_content_matches[-1].group(1))

    answer_start_matches = list(re.finditer(r"<answer>", stripped, flags=re.IGNORECASE))
    if answer_start_matches:
        add(stripped[answer_start_matches[-1].end() :])

    add(re.sub(r"<think>.*?</think>", "", stripped, flags=re.IGNORECASE | re.DOTALL))
    add(re.sub(r"</?answer>", "", stripped, flags=re.IGNORECASE))
    add(stripped)
    return candidates


def _scan_first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        fragment = text[index:]
        try:
            value, _ = decoder.raw_decode(fragment)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value

        close_count = 0
        for end_index, fragment_char in enumerate(fragment):
            if fragment_char != "}":
                continue
            close_count += 1
            candidate = fragment[: end_index + 1]
            repaired = _try_parse_json_object(candidate)
            if repaired is not None:
                return repaired
            if close_count >= 8:
                break
    return None


def _try_parse_json_object(text: str) -> dict[str, Any] | None:
    payload = _try_json_loads_object(text)
    if payload is not None:
        return payload

    repaired_text = _lightweight_json_repair(text)
    if repaired_text == text:
        return None
    return _try_json_loads_object(repaired_text)


def _try_json_loads_object(text: str) -> dict[str, Any] | None:
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _lightweight_json_repair(text: str) -> str:
    repaired = text.strip()
    repaired = re.sub(
        r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)"\s*:',
        r'\1"\2":',
        repaired,
    )
    repaired = re.sub(
        r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:",
        r'\1"\2":',
        repaired,
    )
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def _build_schedule_request_from_payload(
    payload: dict[str, Any] | None,
    *,
    fallback_tz: tzinfo,
) -> ParsedScheduleRequest:
    if payload is None:
        raise RuntimeError("LFM2.5 output is not valid JSON object text.")

    start_raw = payload.get("start")
    end_raw = payload.get("end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise RuntimeError("LFM2.5 output must include string fields: start, end.")

    start_dt = _parse_iso_datetime(start_raw, fallback_tz=fallback_tz)
    end_dt = _parse_iso_datetime(end_raw, fallback_tz=fallback_tz)
    if start_dt is None or end_dt is None:
        raise RuntimeError("LFM2.5 output must use ISO-8601 datetimes for start/end.")
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    location_raw = payload.get("location")
    location = _normalize_location(location_raw if isinstance(location_raw, str) else "")
    return ParsedScheduleRequest(
        query_range=QueryTimeRange(start=start_dt, end=end_dt),
        location=location,
    )


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip()
    return normalized.replace("　", " ")


def _normalize_location(location: str) -> str:
    cleaned = unicodedata.normalize("NFKC", location).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" ,，。.!！?？")
    return re.sub(r"(で|にて|に)$", "", cleaned)


def _thinking_repair_validation_error(
    *,
    model_id: str,
    query_text: str,
    parsed: ParsedScheduleRequest,
    reference_time: datetime,
) -> str | None:
    if not _uses_reasoning_output_mode(model_id):
        return None

    errors: list[str] = []
    normalized_query = unicodedata.normalize("NFKC", query_text)
    lower_query = normalized_query.casefold()
    fallback_tz = reference_time.tzinfo or UTC

    expected_date = _expected_start_date(
        query_text=normalized_query,
        lower_query=lower_query,
        base=reference_time.date(),
    )
    if expected_date is not None and parsed.query_range.start.date() != expected_date:
        errors.append(f"start date must be {expected_date.isoformat()} from relative-day phrase.")

    expected_duration = _latest_duration_minutes(normalized_query)
    if expected_duration is not None:
        actual_duration = int(
            (parsed.query_range.end - parsed.query_range.start).total_seconds() // 60
        )
        if actual_duration != expected_duration:
            errors.append(
                "duration mismatch: expected "
                f"{expected_duration} minutes from latest correction, got {actual_duration} minutes."
            )

    expected_end_clock = _expected_end_clock(normalized_query)
    if expected_end_clock is not None:
        expected_end_date = expected_date or parsed.query_range.start.date()
        expected_end = datetime.combine(
            expected_end_date,
            time(expected_end_clock[0], expected_end_clock[1]),
            tzinfo=fallback_tz,
        )
        expected_end = expected_end.astimezone(parsed.query_range.end.tzinfo)
        if expected_end <= parsed.query_range.start:
            expected_end += timedelta(days=1)
        if parsed.query_range.end != expected_end:
            errors.append(f"end must be {expected_end.isoformat()} from end-time phrase.")

    expected_start_clock = _expected_start_clock(normalized_query)
    if expected_date is not None and expected_start_clock is not None:
        expected_start = datetime.combine(
            expected_date,
            time(expected_start_clock[0], expected_start_clock[1]),
            tzinfo=fallback_tz,
        )
        expected_start = expected_start.astimezone(parsed.query_range.start.tzinfo)
        if parsed.query_range.start != expected_start:
            errors.append(f"start must be {expected_start.isoformat()} from query clock phrase.")
        if expected_duration is not None:
            expected_end = expected_start + timedelta(minutes=expected_duration)
            if parsed.query_range.end != expected_end:
                errors.append(f"end must be {expected_end.isoformat()} from latest duration.")

    if parsed.location and not _location_grounded_in_query(parsed.location, query_text):
        errors.append("location must be copied verbatim from query text.")

    if not errors:
        return None
    return "; ".join(errors)


def _latest_duration_minutes(query_text: str) -> int | None:
    candidates: list[tuple[int, int]] = []
    occupied_ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"(\d{1,4})\s*時間(?:\s*(\d{1,4})\s*分)?", query_text):
        hours = int(match.group(1))
        minutes = int(match.group(2)) if match.group(2) else 0
        candidates.append((match.start(), (hours * 60) + minutes))
        occupied_ranges.append((match.start(), match.end()))
    for match in re.finditer(
        r"(\d{1,4})\s*hours?(?:\s*(\d{1,4})\s*(?:minutes?|mins?))?",
        query_text,
        flags=re.IGNORECASE,
    ):
        hours = int(match.group(1))
        minutes = int(match.group(2)) if match.group(2) else 0
        candidates.append((match.start(), (hours * 60) + minutes))
        occupied_ranges.append((match.start(), match.end()))
    for match in re.finditer(r"(\d{1,4})\s*(?:分|minutes?|mins?)", query_text, flags=re.IGNORECASE):
        span = (match.start(), match.end())
        if any(_ranges_overlap(span, occupied) for occupied in occupied_ranges):
            continue
        candidates.append((match.start(), int(match.group(1))))

    for match in re.finditer(
        r"(?:actually|correction:?|instead|no\s+make\s+it|make\s+it)\s*(\d{1,4})\b",
        query_text,
        flags=re.IGNORECASE,
    ):
        candidates.append((match.start(1), int(match.group(1))))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _expected_start_clock(query_text: str) -> tuple[int, int] | None:
    start_marker_match = re.search(
        r"開始\s*((朝|午前|午後|夜|夕方|深夜)?\s*(\d{1,2})時(?!間)(?:\s*(\d{1,2})分|半)?|正午|真夜中)",
        query_text,
    )
    if start_marker_match is not None:
        return _parse_japanese_clock(
            start_marker_match.group(1),
            assume_daytime_for_ambiguous=False,
        )

    start_marker_match_en = re.search(
        r"start(?:ing)?\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)|noon|midnight)",
        query_text,
        flags=re.IGNORECASE,
    )
    if start_marker_match_en is not None:
        return _parse_english_clock(start_marker_match_en.group(1))

    range_start_en = re.search(
        r"\b(\d{1,2}(?::\d{2})?)\s*(am|pm)?\s*(?:to|until|till|-)\s*"
        r"(\d{1,2}(?::\d{2})?)\s*(am|pm)\b",
        query_text,
        flags=re.IGNORECASE,
    )
    if range_start_en is not None:
        start_token = range_start_en.group(1)
        start_meridiem = range_start_en.group(2) or range_start_en.group(4)
        return _parse_english_clock(f"{start_token} {start_meridiem}")

    first_jp = re.search(
        r"(正午|真夜中|(朝|午前|午後|夜|夕方|深夜)?\s*(\d{1,2})時(?!間)(?:\s*(\d{1,2})分|半)?)",
        query_text,
    )
    if first_jp is not None:
        candidate_text = first_jp.group(0)
        candidate_clock = _parse_japanese_clock(candidate_text)
        if candidate_clock is not None and 13 <= candidate_clock[0] <= 23:
            following_range_end = re.search(
                r"から\s*((?:朝|午前|午後|夜|夕方|深夜)?\s*\d{1,2}時(?!間)(?:\s*\d{1,2}分|半)?|正午|真夜中)",
                query_text[first_jp.end() :],
            )
            if following_range_end is not None:
                following_clock = _parse_japanese_clock(
                    following_range_end.group(1),
                    assume_daytime_for_ambiguous=False,
                )
                if following_clock is not None and following_clock[0] >= 12:
                    return _parse_japanese_clock(
                        candidate_text,
                        assume_daytime_for_ambiguous=False,
                    )
        return _parse_japanese_clock(first_jp.group(0))
    first_en = re.search(
        r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)|noon|midnight)\b",
        query_text,
        flags=re.IGNORECASE,
    )
    if first_en is not None:
        return _parse_english_clock(first_en.group(1))
    return None


def _parse_japanese_clock(
    value: str,
    *,
    assume_daytime_for_ambiguous: bool = True,
) -> tuple[int, int] | None:
    if "正午" in value:
        return 12, 0
    if "真夜中" in value:
        return 0, 0

    match = re.search(
        r"(朝|午前|午後|夜|夕方|深夜)?\s*(\d{1,2})時(?!間)(?:\s*(\d{1,2})分|半)?", value
    )
    if match is None:
        return None

    marker = (match.group(1) or "").strip()
    hour = int(match.group(2))
    minute_token = match.group(3)
    minute = 30 if "半" in match.group(0) and minute_token is None else int(minute_token or "0")
    if marker in {"午後", "夜", "夕方"}:
        if hour < 12:
            hour += 12
    elif marker in {"朝", "午前", "深夜"}:
        if hour == 12:
            hour = 0
    elif assume_daytime_for_ambiguous and 1 <= hour <= 11:
        # Business-hour default for ambiguous Japanese times.
        hour += 12
    return hour % 24, minute


def _parse_english_clock(value: str) -> tuple[int, int] | None:
    if re.search(r"\bnoon\b", value, flags=re.IGNORECASE):
        return 12, 0
    if re.search(r"\bmidnight\b", value, flags=re.IGNORECASE):
        return 0, 0

    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", value, flags=re.IGNORECASE)
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3).lower()
    if meridiem == "am":
        if hour == 12:
            hour = 0
    elif hour < 12:
        hour += 12
    return hour, minute


def _expected_start_date(*, query_text: str, lower_query: str, base: date) -> date | None:
    if "明後日" in query_text or "day after tomorrow" in lower_query:
        return base + timedelta(days=2)
    if "明日" in query_text or "tomorrow" in lower_query:
        return base + timedelta(days=1)

    days_after_match = re.search(r"(\d{1,3})日後", query_text)
    if days_after_match is not None:
        return base + timedelta(days=int(days_after_match.group(1)))

    in_days_match = re.search(r"\bin\s+(\d{1,3})\s+days?\b", lower_query)
    if in_days_match is not None:
        return base + timedelta(days=int(in_days_match.group(1)))
    return None


def _expected_end_clock(query_text: str) -> tuple[int, int] | None:
    jp_until_matches = re.finditer(
        r"((?:朝|午前|午後|夜|夕方|深夜)?\s*\d{1,2}時(?!間)(?:\s*\d{1,2}分|半)?|正午|真夜中)\s*(?:まで|終了|終わり)",
        query_text,
    )
    jp_candidates = [
        parsed
        for parsed in (
            _parse_japanese_clock(match.group(1), assume_daytime_for_ambiguous=False)
            for match in jp_until_matches
        )
        if parsed is not None
    ]
    if jp_candidates:
        return jp_candidates[-1]

    jp_from_matches = re.finditer(
        r"から\s*((?:朝|午前|午後|夜|夕方|深夜)?\s*\d{1,2}時(?!間)(?:\s*\d{1,2}分|半)?|正午|真夜中)",
        query_text,
    )
    jp_from_candidates = [
        parsed
        for parsed in (
            _parse_japanese_clock(match.group(1), assume_daytime_for_ambiguous=False)
            for match in jp_from_matches
        )
        if parsed is not None
    ]
    if jp_from_candidates:
        return jp_from_candidates[-1]

    en_end_matches = re.finditer(
        r"(?:to|until|till|end(?:ing)?(?:\s+at|\s+by)?)\s*"
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)|noon|midnight)",
        query_text,
        flags=re.IGNORECASE,
    )
    en_candidates = [
        parsed
        for parsed in (_parse_english_clock(match.group(1)) for match in en_end_matches)
        if parsed is not None
    ]
    if en_candidates:
        return en_candidates[-1]
    return None


def _apply_explicit_query_constraints(
    *,
    query_text: str,
    parsed: ParsedScheduleRequest,
    reference_time: datetime,
) -> ParsedScheduleRequest:
    normalized_query = unicodedata.normalize("NFKC", query_text)
    lower_query = normalized_query.casefold()
    expected_date = _expected_start_date(
        query_text=normalized_query,
        lower_query=lower_query,
        base=reference_time.date(),
    )
    expected_start_clock = _expected_start_clock(normalized_query)
    expected_end_clock = _expected_end_clock(normalized_query)
    expected_duration = _latest_duration_minutes(normalized_query)

    start = parsed.query_range.start
    end = parsed.query_range.end
    tz = start.tzinfo or reference_time.tzinfo or UTC
    start = start.astimezone(tz)
    end = end.astimezone(tz)
    changed = False

    if expected_date is not None or expected_start_clock is not None:
        target_date = expected_date or start.date()
        target_hour, target_minute = start.hour, start.minute
        if expected_start_clock is not None:
            target_hour, target_minute = expected_start_clock
        constrained_start = datetime.combine(
            target_date,
            time(target_hour, target_minute),
            tzinfo=tz,
        )
        if constrained_start != start:
            start = constrained_start
            changed = True

    if expected_end_clock is not None:
        constrained_end = datetime.combine(
            start.date(),
            time(expected_end_clock[0], expected_end_clock[1]),
            tzinfo=tz,
        )
        if constrained_end <= start:
            constrained_end += timedelta(days=1)
        if constrained_end != end:
            end = constrained_end
            changed = True
    elif expected_duration is not None:
        constrained_end = start + timedelta(minutes=expected_duration)
        if constrained_end != end:
            end = constrained_end
            changed = True
    elif changed:
        original_duration = parsed.query_range.end - parsed.query_range.start
        if original_duration.total_seconds() > 0:
            end = start + original_duration

    if end <= start:
        end = start + timedelta(days=1)
        changed = True

    if not changed:
        return parsed
    return ParsedScheduleRequest(
        query_range=QueryTimeRange(start=start, end=end),
        location=parsed.location,
    )


def _ranges_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _location_grounded_in_query(location: str, query_text: str) -> bool:
    location_compact = _compact_for_containment(location)
    query_compact = _compact_for_containment(query_text)
    if not location_compact:
        return True
    return location_compact in query_compact


def _compact_for_containment(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s,，。.!！?？'\"`]+", "", normalized)


def _parse_iso_datetime(value: str, *, fallback_tz: tzinfo) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=fallback_tz)
    return parsed.astimezone(fallback_tz)


def _read_lfm_model_id() -> str:
    model_id = os.environ.get("BRIDGECAL_LFM25_LOCAL_MODEL", "").strip()
    if model_id:
        return model_id
    return "LiquidAI/LFM2.5-1.2B-Instruct"


def _is_lfm_thinking_model(model_id: str) -> bool:
    return "thinking" in model_id.casefold()


def _is_qwen3_model(model_id: str) -> bool:
    lowered = model_id.casefold()
    return "qwen3" in lowered and "qwen" in lowered


def _uses_reasoning_output_mode(model_id: str) -> bool:
    return _is_lfm_thinking_model(model_id) or _is_qwen3_model(model_id)


def _should_force_assistant_json_prefill(*, model_id: str, thinking_mode: bool) -> bool:
    if not thinking_mode:
        return False
    # Let thinking-capable models decide whether to emit <think> blocks.
    return False


def _chat_template_kwargs(*, model_id: str, thinking_mode: bool) -> dict[str, Any]:
    if _is_qwen3_model(model_id):
        return {"enable_thinking": thinking_mode}
    return {}


def _effective_max_new_tokens(*, model_id: str, requested: int) -> int:
    if _is_qwen3_model(model_id) and requested < 640:
        # Qwen3 reasoning output often needs more budget to emit </think> and final JSON.
        return 640
    return requested


def _read_lfm_max_new_tokens() -> int:
    raw = os.environ.get("BRIDGECAL_LFM25_LOCAL_MAX_NEW_TOKENS", "").strip()
    if not raw:
        return 220
    try:
        value = int(raw)
    except ValueError:
        return 220
    return _normalize_max_new_tokens(value)


def _normalize_max_new_tokens(value: int) -> int:
    if value < 32:
        return 32
    if value > 16_384:
        return 16_384
    return value


def _read_lfm_seed() -> int:
    return _read_env_int(
        "BRIDGECAL_LFM25_LOCAL_SEED",
        default=42,
        minimum=-1,
        maximum=2147483647,
    )


def _read_lfm_device_mode() -> str:
    value = os.environ.get("BRIDGECAL_LFM25_LOCAL_DEVICE", "").strip().lower()
    if value in {"auto", "cpu"}:
        return value
    return "cpu"


def _read_lfm_torch_dtype() -> str:
    value = os.environ.get("BRIDGECAL_LFM25_LOCAL_TORCH_DTYPE", "").strip()
    if value:
        return value
    return "float32"


def _read_lfm_allow_remote_code() -> bool:
    return _read_env_bool("BRIDGECAL_LFM25_ALLOW_REMOTE_CODE", default=False)


def _read_env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _read_env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _event_range_utc(event: CanonicalEvent) -> tuple[datetime, datetime, bool]:
    local_tz = _local_timezone(datetime.now().astimezone())
    if event.time.is_all_day:
        start_date = event.time.start_date
        if start_date is None:
            raise ValueError("All-day event is missing start_date.")
        end_date = event.time.end_date or (start_date + timedelta(days=1))
        start_dt = datetime.combine(start_date, time.min, tzinfo=local_tz)
        end_dt = datetime.combine(end_date, time.min, tzinfo=local_tz)
        return _to_utc(start_dt), _to_utc(end_dt), True

    if event.time.start_dt is None or event.time.end_dt is None:
        raise ValueError("Timed event is missing start/end.")
    start_dt = _ensure_aware(event.time.start_dt, fallback_tz=local_tz)
    end_dt = _ensure_aware(event.time.end_dt, fallback_tz=local_tz)
    return _to_utc(start_dt), _to_utc(end_dt), False


def _ensure_aware(value: datetime, *, fallback_tz: tzinfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=fallback_tz)
    return value


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _overlaps(*, start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and end_a > start_b


def _local_timezone(now: datetime) -> tzinfo:
    return now.tzinfo or UTC
