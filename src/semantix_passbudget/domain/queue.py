"""Queue comparator and exact rate-timeline primitives.

The allocation loop itself lives in `ledger.py`; this module owns only the pieces that decide
*which* payload comes next and *how long* a given byte count takes on a session's rate timeline.
All arithmetic is exact rational; no binary float reaches a byte or a timestamp.
"""

from __future__ import annotations

from fractions import Fraction

from .enums import CapacityProvider, ServiceClass
from .models import CapacityProfile, Payload
from .scheduler import Candidate
from .time import UtcInstant

QUEUE_POLICY_REVISION = "DEADLINE_SEVERITY_CORE_V1"
SERVICE_CLASS_RANK_REVISION = "MANDATORY_0_PRIORITY_1_BEST_EFFORT_2_V1"

_SERVICE_RANK = {
    ServiceClass.MANDATORY: 0,
    ServiceClass.PRIORITY: 1,
    ServiceClass.BEST_EFFORT: 2,
}


def queue_order_key(payload: Payload) -> tuple[int, int, int, int, int, str]:
    """`DEADLINE_SEVERITY_CORE_V1` comparator.

    service_class -> deadline_at ASC (absent deadlines last) -> severity_rank DESC ->
    mission_priority DESC -> queue_sequence ASC -> stable key.
    """
    deadline_missing = payload.deadline_at is None
    deadline = payload.deadline_at.microseconds if payload.deadline_at else 0
    return (
        _SERVICE_RANK[payload.service_class],
        int(deadline_missing),
        deadline,
        -payload.deadline_severity,
        -payload.mission_priority,
        f"{payload.queue_sequence:020d}/{payload.stable_key}",
    )


def round_half_even(value: Fraction) -> int:
    """Quantize a rational microsecond count to the nearest tick, ties to even."""
    quotient, remainder = divmod(value.numerator, value.denominator)
    doubled = remainder * 2
    if doubled < value.denominator:
        return quotient
    if doubled > value.denominator:
        return quotient + 1
    return quotient if quotient % 2 == 0 else quotient + 1


def unreserved_spans(
    profile: CapacityProfile,
    session_start_us: int,
    start_us: int,
    end_us: int,
) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = [(start_us, end_us)]
    for reserve in profile.time_reserves:
        reserve_start = session_start_us + reserve.start_offset_us
        reserve_end = session_start_us + reserve.end_offset_us
        next_spans: list[tuple[int, int]] = []
        for left, right in spans:
            if reserve_end <= left or right <= reserve_start:
                next_spans.append((left, right))
                continue
            if left < reserve_start:
                next_spans.append((left, reserve_start))
            if reserve_end < right:
                next_spans.append((reserve_end, right))
        spans = next_spans
    return tuple(spans)


def allocation_end(
    session: Candidate,
    profile: CapacityProfile,
    start: UtcInstant,
    byte_count: int,
) -> UtcInstant:
    if profile.provider is CapacityProvider.FIXED_CAPACITY_PER_CONTACT:
        # A fixed-capacity provider has no time-distribution evidence. The only
        # defensible P0 interval is the full modeled session.
        return session.interval.end

    bits_left = Fraction(byte_count * 8)
    factor = profile.active_efficiency or Fraction(1)
    cursor_us = start.microseconds
    session_start_us = session.interval.start.microseconds
    for segment in sorted(profile.rate_segments, key=lambda item: item.ordinal):
        segment_start = session_start_us + segment.start_offset_us
        segment_end = min(
            session_start_us + segment.end_offset_us,
            session.interval.end.microseconds,
        )
        active_start = max(cursor_us, segment_start)
        effective_rate = segment.rate.fraction * factor
        if effective_rate == 0:
            continue
        for span_start, span_end in unreserved_spans(
            profile, session_start_us, active_start, segment_end
        ):
            if span_start >= span_end:
                continue
            available_bits = effective_rate * Fraction(span_end - span_start, 1_000_000)
            if bits_left <= available_bits:
                elapsed_us = bits_left / effective_rate * 1_000_000
                end_us = span_start + round_half_even(elapsed_us)
                return UtcInstant(min(end_us, session.interval.end.microseconds))
            bits_left -= available_bits
            cursor_us = span_end
    return session.interval.end


def rate_bytes_remaining(session: Candidate, profile: CapacityProfile, cursor: UtcInstant) -> int:
    """Whole logical bytes still deliverable in `session` from `cursor` onwards."""
    if profile.provider is CapacityProvider.FIXED_CAPACITY_PER_CONTACT:
        return session.capacity_bytes
    total_bits = Fraction(0)
    session_start_us = session.interval.start.microseconds
    for segment in profile.rate_segments:
        segment_start = session_start_us + segment.start_offset_us
        segment_end = min(
            session_start_us + segment.end_offset_us,
            session.interval.end.microseconds,
        )
        active_start = max(cursor.microseconds, segment_start)
        for span_start, span_end in unreserved_spans(
            profile, session_start_us, active_start, segment_end
        ):
            if span_start < span_end:
                total_bits += segment.rate.fraction * Fraction(span_end - span_start, 1_000_000)
    if profile.active_efficiency is not None:
        total_bits *= profile.active_efficiency
    return total_bits.numerator // (total_bits.denominator * 8)
