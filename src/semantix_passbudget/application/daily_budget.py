"""UTC per-day transfer budget — a read-only re-aggregation of an existing run result.

This module derives "how much can be delivered on each UTC calendar date?" from a run result
that the engine already computed. It performs no new physics: it reads
``scheduled_sessions[].capacity_bytes`` (post-conflict selected capacity),
``candidate_sessions[].capacity_bytes`` (pre-conflict candidate capacity),
``geometric_accesses[].true_aos`` (geometric contact instants) and
``metrics.scheduled_unique_capacity_bytes`` (period total) and buckets them by the UTC calendar
date of each session's ``usable_start``.

The public API contract fixes the aggregation basis:
``AGGREGATION_BASIS = "UTC_DATE_OF_SESSION_START"`` — every selected/candidate session is
attributed *in full* to the UTC calendar day of its start. A session that crosses midnight is
counted wholly on its start day: the stored session carries one exact integer capacity and there
is no physically-unique way to split that integer across instants without re-running the engine,
so start-day attribution is an explicit, displayed convention rather than a time-ratio guess.

Because each selected session lands in exactly one day exactly once, the daily scheduled capacities
always sum back to ``metrics.scheduled_unique_capacity_bytes`` — a sum-preservation invariant the
response reports so a caller can verify it. Neither the run result document nor its hash is touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

AGGREGATION_BASIS = "UTC_DATE_OF_SESSION_START"

_NOTICE = (
    "일별 값은 세션을 시작 UTC 날짜에 귀속한 집계이며, "
    "자정을 가로지르는 세션은 시작일에 전량 계상됩니다."
)


class DailyBudgetError(ValueError):
    """The result document is missing a field the aggregation strictly needs."""


def _parse_instant(value: str) -> datetime:
    """Parse an engine ISO instant (``...Z`` with microseconds) as an aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_date_of(value: str) -> date:
    return _parse_instant(value).date()


@dataclass(frozen=True, slots=True)
class _DayAccumulator:
    geometric_contact_count: int = 0
    scheduled_session_count: int = 0
    scheduled_capacity_bytes: int = 0
    candidate_session_count: int = 0
    candidate_capacity_sum_bytes: int = 0


def _window_dates(window: dict[str, Any] | None) -> tuple[date | None, date | None]:
    """First and last UTC calendar dates covered by a half-open ``[start, end)`` window.

    ``end`` is exclusive, so an ``end`` that lands exactly on midnight does not add a trailing
    empty day: the last covered date is that of ``end - 1µs``. Returns ``(None, None)`` when no
    window is available (e.g. a run restored from a tier that did not carry the input payload).
    """
    if not window:
        return (None, None)
    start_raw = window.get("start")
    end_raw = window.get("end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return (None, None)
    start = _parse_instant(start_raw)
    end = _parse_instant(end_raw)
    if end <= start:
        return (start.date(), start.date())
    last = (end - timedelta(microseconds=1)).date()
    return (start.date(), last)


def daily_budget(result: dict[str, Any], analysis_window: dict[str, Any] | None) -> dict[str, Any]:
    """Aggregate a run ``result`` into per-UTC-date transfer budget rows.

    ``analysis_window`` (``{"start", "end"}`` ISO, or ``None``) fixes the reported period and lets
    days inside the window with no contact appear as an explicit ``0`` (KNOWN_ZERO) rather than
    being absent. When it is ``None`` the period falls back to the observed session/contact span,
    and boundary partial-day flags are not asserted (there is no window to compare against).
    """
    scheduled = result.get("scheduled_sessions") or []
    candidates = result.get("candidate_sessions") or []
    accesses = result.get("geometric_accesses") or []
    metrics = result.get("metrics") or {}
    calculation_status = str(result.get("calculation_status", "UNKNOWN"))

    days: dict[date, _DayAccumulator] = {}

    def _bump(key: date, **deltas: int) -> None:
        current = days.get(key, _DayAccumulator())
        days[key] = _DayAccumulator(
            geometric_contact_count=current.geometric_contact_count
            + deltas.get("geometric_contact_count", 0),
            scheduled_session_count=current.scheduled_session_count
            + deltas.get("scheduled_session_count", 0),
            scheduled_capacity_bytes=current.scheduled_capacity_bytes
            + deltas.get("scheduled_capacity_bytes", 0),
            candidate_session_count=current.candidate_session_count
            + deltas.get("candidate_session_count", 0),
            candidate_capacity_sum_bytes=current.candidate_capacity_sum_bytes
            + deltas.get("candidate_capacity_sum_bytes", 0),
        )

    for access in accesses:
        aos = access.get("true_aos")
        if isinstance(aos, str):
            _bump(_utc_date_of(aos), geometric_contact_count=1)

    for session in candidates:
        start = session.get("usable_start")
        if not isinstance(start, str):
            continue
        capacity = session.get("capacity_bytes")
        _bump(
            _utc_date_of(start),
            candidate_session_count=1,
            candidate_capacity_sum_bytes=int(capacity) if isinstance(capacity, int) else 0,
        )

    for session in scheduled:
        start = session.get("usable_start")
        if not isinstance(start, str):
            continue
        capacity = session.get("capacity_bytes")
        _bump(
            _utc_date_of(start),
            scheduled_session_count=1,
            scheduled_capacity_bytes=int(capacity) if isinstance(capacity, int) else 0,
        )

    first_date, last_date = _window_dates(analysis_window)
    if first_date is not None and last_date is not None:
        cursor = first_date
        while cursor <= last_date:
            days.setdefault(cursor, _DayAccumulator())
            cursor += timedelta(days=1)

    if first_date is not None and analysis_window is not None:
        window_start = _parse_instant(analysis_window["start"])
        window_end = _parse_instant(analysis_window["end"])
    else:
        window_start = None
        window_end = None

    def _is_partial(day: date) -> bool:
        if window_start is None or window_end is None:
            return False
        day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        return window_start > day_start or window_end < day_end

    day_rows: list[dict[str, Any]] = []
    for day in sorted(days):
        acc = days[day]
        day_rows.append(
            {
                "utc_date": day.isoformat(),
                "is_partial": _is_partial(day),
                "geometric_contact_count": acc.geometric_contact_count,
                "scheduled_session_count": acc.scheduled_session_count,
                "scheduled_capacity_bytes": acc.scheduled_capacity_bytes,
                "candidate_session_count": acc.candidate_session_count,
                "candidate_capacity_sum_bytes": acc.candidate_capacity_sum_bytes,
            }
        )

    period_total = metrics.get("scheduled_unique_capacity_bytes")
    daily_sum = sum(row["scheduled_capacity_bytes"] for row in day_rows)
    sum_preserved = isinstance(period_total, int) and daily_sum == period_total

    window_out: dict[str, str] | None = None
    if isinstance(analysis_window, dict):
        start_raw = analysis_window.get("start")
        end_raw = analysis_window.get("end")
        if isinstance(start_raw, str) and isinstance(end_raw, str):
            window_out = {"start": start_raw, "end": end_raw}

    return {
        "run_id": str(result.get("run_id", "")) or None,
        "analysis_window": window_out,
        "aggregation_basis": AGGREGATION_BASIS,
        "calculation_status": calculation_status,
        "period_scheduled_unique_capacity_bytes": period_total,
        "period_scheduled_capacity_from_days_bytes": daily_sum,
        "sum_preserved": sum_preserved,
        "days": day_rows,
        "notice": _NOTICE,
    }
