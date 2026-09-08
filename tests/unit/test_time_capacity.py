from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from semantix_passbudget.domain.capacity import calculate_contact_capacity
from semantix_passbudget.domain.enums import (
    CalculationStatus,
    CapacityProvider,
    DecisionGrade,
    EvidenceState,
    RateSemantics,
)
from semantix_passbudget.domain.errors import DomainValidationError
from semantix_passbudget.domain.models import (
    CapacityProfile,
    ExactRate,
    RateSegment,
    TimeReserve,
)
from semantix_passbudget.domain.time import TimeInterval, UtcInstant


def test_strict_utc_and_interval_contract() -> None:
    parsed = UtcInstant.parse("2027-01-01T00:00:00.123456Z")
    assert parsed.isoformat() == "2027-01-01T00:00:00.123456Z"
    for invalid in (
        "2027-01-01T09:00:00+09:00",
        "2027-01-01T00:00:00.1234567Z",
        "2027-01-01T23:59:60Z",
    ):
        with pytest.raises(DomainValidationError):
            UtcInstant.parse(invalid)


def test_golden_a1_exact_rate(golden_snapshot: object) -> None:
    snapshot = golden_snapshot
    station = next(item for item in snapshot.stations if item.stable_key == "GS-A")
    contact = next(item for item in snapshot.contacts if item.stable_key == "A1")
    result = calculate_contact_capacity(contact, station.capacity, snapshot.analysis_window)
    assert result.modeled_interval is not None
    assert result.modeled_interval.start.isoformat() == "2027-01-01T00:11:00.000000Z"
    assert result.modeled_interval.end.isoformat() == "2027-01-01T00:19:00.000000Z"
    assert result.capacity_bytes == 60_000_000
    assert result.grade is DecisionGrade.CONCEPT_ONLY


@pytest.mark.parametrize(
    ("guard_us", "expected_status", "expected_capacity"),
    [
        (49_999_999, CalculationStatus.COMPUTED, 1),
        (50_000_000, CalculationStatus.KNOWN_ZERO, 0),
        (50_000_001, CalculationStatus.KNOWN_ZERO, 0),
    ],
)
def test_guard_boundary(
    golden_snapshot: object,
    guard_us: int,
    expected_status: CalculationStatus,
    expected_capacity: int,
) -> None:
    snapshot = golden_snapshot
    base = snapshot.stations[0].capacity
    profile = replace(
        base,
        acquisition_guard_us=guard_us,
        release_guard_us=guard_us,
        rate_segments=(RateSegment(0, 0, 100_000_000, ExactRate(4_000_000, 1)),),
    )
    contact = replace(
        snapshot.contacts[0],
        true_interval=TimeInterval(
            UtcInstant.parse("2027-01-01T00:00:00Z"),
            UtcInstant.parse("2027-01-01T00:01:40Z"),
        ),
    )
    result = calculate_contact_capacity(contact, profile, snapshot.analysis_window)
    assert result.status is expected_status
    assert result.capacity_bytes == expected_capacity


def test_unknown_rate_blocks_only_capacity(golden_snapshot: object) -> None:
    snapshot = golden_snapshot
    station = snapshot.stations[0]
    profile = replace(station.capacity, rate_unknown=True, rate_segments=())
    result = calculate_contact_capacity(snapshot.contacts[0], profile, snapshot.analysis_window)
    assert result.modeled_interval is not None
    assert result.capacity_bytes is None
    assert result.status is CalculationStatus.BLOCKED
    assert result.grade is DecisionGrade.BLOCKED


def test_fixed_provider_factor_conflict(golden_snapshot: object) -> None:
    conflicting = CapacityProfile(
        provider=CapacityProvider.FIXED_CAPACITY_PER_CONTACT,
        rate_semantics=None,
        acquisition_guard_us=0,
        release_guard_us=0,
        rate_segments=(RateSegment(0, 0, 1_000_000, ExactRate(8, 1)),),
        fixed_capacity_bytes=10,
        byte_reserve=0,
        active_efficiency=Fraction(1, 2),
        rate_unknown=False,
        evidence_state=EvidenceState.PROXY,
        source_revision_id="TEST-R1",
        rationale="Test-only conflict.",
    )
    with pytest.raises(DomainValidationError) as raised:
        conflicting.validate()
    assert raised.value.detail.code == "INPUT_FACTOR_CONFLICT"


def test_fixed_capacity_is_not_scaled_after_guard(golden_snapshot: object) -> None:
    snapshot = golden_snapshot
    base = snapshot.stations[0].capacity
    fixed = replace(
        base,
        provider=CapacityProvider.FIXED_CAPACITY_PER_CONTACT,
        rate_semantics=None,
        acquisition_guard_us=100_000_000,
        release_guard_us=100_000_000,
        rate_segments=(),
        fixed_capacity_bytes=123_456_789,
        byte_reserve=0,
        active_efficiency=None,
        measurement_point=None,
        rate_scope=None,
        accounted_effects=(),
    )
    fixed.validate()
    result = calculate_contact_capacity(snapshot.contacts[0], fixed, snapshot.analysis_window)
    assert result.modeled_interval is not None
    assert result.capacity_bytes == 123_456_789


@pytest.mark.parametrize(
    ("semantics", "rate", "factor", "expected"),
    [
        (RateSemantics.CODED_BITRATE, 1_000_000, Fraction(9, 25), 4_500_000),
        (RateSemantics.NET_PAYLOAD_BITRATE_PRE_LOSS, 800_000, Fraction(3, 4), 7_500_000),
        (RateSemantics.APPLICATION_GOODPUT, 600_000, None, 7_500_000),
    ],
)
def test_exact_rate_semantic_normalization(
    golden_snapshot: object,
    semantics: RateSemantics,
    rate: int,
    factor: Fraction | None,
    expected: int,
) -> None:
    snapshot = golden_snapshot
    contact = replace(
        snapshot.contacts[0],
        true_interval=TimeInterval(
            UtcInstant.parse("2027-01-01T00:00:00Z"),
            UtcInstant.parse("2027-01-01T00:01:40Z"),
        ),
    )
    profile = replace(
        snapshot.stations[0].capacity,
        rate_semantics=semantics,
        acquisition_guard_us=0,
        release_guard_us=0,
        rate_segments=(RateSegment(0, 0, 100_000_000, ExactRate(rate, 1)),),
        active_efficiency=factor,
    )
    profile.validate()
    result = calculate_contact_capacity(contact, profile, snapshot.analysis_window)
    assert result.capacity_bytes == expected


def test_byte_and_time_reserves_are_exact(golden_snapshot: object) -> None:
    snapshot = golden_snapshot
    station = snapshot.stations[0]
    contact = snapshot.contacts[0]
    byte_reserved = calculate_contact_capacity(
        contact,
        replace(station.capacity, byte_reserve=5_000_000),
        snapshot.analysis_window,
    )
    assert byte_reserved.capacity_bytes == 55_000_000

    time_reserved = calculate_contact_capacity(
        contact,
        replace(
            station.capacity,
            time_reserves=(TimeReserve(120_000_000, 180_000_000),),
        ),
        snapshot.analysis_window,
    )
    assert time_reserved.capacity_bytes == 48_750_000

    exhausted = calculate_contact_capacity(
        contact,
        replace(station.capacity, byte_reserve=60_000_000),
        snapshot.analysis_window,
    )
    assert exhausted.status is CalculationStatus.KNOWN_ZERO
    assert exhausted.capacity_bytes == 0
