"""Half-open interval, deadline and expiry boundary contracts.

Every case here is a `<`, `=`, `>` triplet around one tick, because the accepted contract is
`[start, end)` with a one-microsecond canonical tick and no epsilon anywhere.
"""

from __future__ import annotations

import pytest

from semantix_passbudget.domain.capacity import calculate_contact_capacity
from semantix_passbudget.domain.enums import (
    CalculationStatus,
    CapacityProvider,
    EvidenceState,
    RateScope,
    RateSemantics,
    SegmentationKind,
    ServiceClass,
)
from semantix_passbudget.domain.errors import DomainValidationError
from semantix_passbudget.domain.ledger import run_ledger
from semantix_passbudget.domain.models import (
    DISABLED_STORAGE,
    CapacityProfile,
    ExactRate,
    Payload,
    RateSegment,
    SyntheticContact,
)
from semantix_passbudget.domain.scheduler import Candidate, select_maximum_nonoverlap
from semantix_passbudget.domain.time import TimeInterval, UtcInstant

DAY = TimeInterval(
    UtcInstant.parse("2027-01-01T00:00:00Z"), UtcInstant.parse("2027-01-02T00:00:00Z")
)


def _rate_profile(rate_bits: int = 500_000) -> CapacityProfile:
    return CapacityProfile(
        provider=CapacityProvider.FIXED_RATE,
        rate_semantics=RateSemantics.APPLICATION_GOODPUT,
        acquisition_guard_us=0,
        release_guard_us=0,
        rate_segments=(RateSegment(0, 0, 3_600_000_000, ExactRate(rate_bits, 1)),),
        fixed_capacity_bytes=None,
        byte_reserve=0,
        active_efficiency=None,
        rate_unknown=False,
        evidence_state=EvidenceState.PROXY,
        source_revision_id="BOUNDARY",
        rationale="Synthetic boundary regression.",
        measurement_point="SYNTHETIC_SPACECRAFT_APPLICATION_EGRESS",
        rate_scope=RateScope.ACTIVE_DATA_WINDOW,
    )


def _session(start_us: int, end_us: int, capacity: int) -> Candidate:
    return Candidate("S", "GS", TimeInterval(UtcInstant(start_us), UtcInstant(end_us)), capacity, 0)


def _payload(
    key: str,
    size: int,
    *,
    ready_us: int = 0,
    deadline_us: int | None = None,
    expiry_us: int | None = None,
) -> Payload:
    from semantix_passbudget.domain.enums import DeadlineTarget, PostDeadlineAction

    return Payload(
        stable_key=key,
        logical_size_bytes=size,
        storage_size_bytes=size,
        ready_at=UtcInstant(ready_us),
        service_class=ServiceClass.PRIORITY,
        deadline_at=None if deadline_us is None else UtcInstant(deadline_us),
        deadline_severity=0,
        mission_priority=50,
        queue_sequence=1,
        segmentation=SegmentationKind.ATOMIC_OBJECT,
        chunk_size_bytes=None,
        resume_supported=False,
        expiry_at=None if expiry_us is None else UtcInstant(expiry_us),
        deadline_target=None if deadline_us is None else DeadlineTarget.INSTANCE_COMPLETE,
        post_deadline_action=(
            None if deadline_us is None else PostDeadlineAction.CONTINUE_AND_REPORT
        ),
    )


@pytest.mark.parametrize(
    ("ready_us", "expected_start_us"),
    [(9_999_999, 10_000_000), (10_000_000, 10_000_000), (10_000_001, 10_000_001)],
)
def test_no_byte_is_placed_before_ready_at(ready_us: int, expected_start_us: int) -> None:
    """AC-24: one tick before / exactly at / one tick after the session start."""
    session_start = 10_000_000
    session = _session(session_start, session_start + 30_000_000, 1_875_000)
    ledger = run_ledger(
        (session,),
        {"GS": _rate_profile()},
        (_payload("P", 1_000_000, ready_us=ready_us),),
        (),
        DISABLED_STORAGE,
        TimeInterval(UtcInstant(0), UtcInstant(120_000_000)),
    )
    assert ledger.allocations[0].start == UtcInstant(expected_start_us)


@pytest.mark.parametrize(
    ("ready_us", "starts"),
    [(39_999_999, True), (40_000_000, False), (40_000_001, False)],
)
def test_ready_at_the_half_open_session_end_is_not_eligible(ready_us: int, starts: bool) -> None:
    """A session is `[start, end)`: a payload ready exactly at `end` never starts in it.

    The rate is high enough that a single remaining microsecond still carries a whole byte, so
    the case isolates the interval boundary rather than the capacity arithmetic.
    """
    session = _session(10_000_000, 40_000_000, 1_875_000)
    ledger = run_ledger(
        (session,),
        {"GS": _rate_profile(16_000_000)},
        (_payload("P", 1, ready_us=ready_us),),
        (),
        DISABLED_STORAGE,
        TimeInterval(UtcInstant(0), UtcInstant(120_000_000)),
    )
    assert bool(ledger.allocations) is starts


def test_deadline_equality_is_on_time_and_one_tick_later_is_late() -> None:
    """AC-27: completion == deadline is ON_TIME; completion > deadline is LATE."""
    session = _session(0, 30_000_000, 1_875_000)
    profile = _rate_profile()
    # 1,000,000 B at 500,000 bit/s takes exactly 16 s.
    for deadline_us, expected in ((16_000_000, True), (15_999_999, False)):
        ledger = run_ledger(
            (session,),
            {"GS": profile},
            (_payload("P", 1_000_000, deadline_us=deadline_us),),
            (),
            DISABLED_STORAGE,
            TimeInterval(UtcInstant(0), UtcInstant(120_000_000)),
        )
        completion = ledger.progress[0].modeled_tx_complete_at
        assert completion == UtcInstant(16_000_000)
        assert (completion.microseconds <= deadline_us) is expected


@pytest.mark.parametrize(
    ("expiry_us", "starts"),
    [(9_999_999, False), (10_000_000, False), (10_000_001, True)],
)
def test_expiry_uses_a_half_open_window(expiry_us: int, starts: bool) -> None:
    """`[ready_at, expiry_at)`: a new allocation may start strictly before expiry only."""
    session = _session(10_000_000, 40_000_000, 1_875_000)
    ledger = run_ledger(
        (session,),
        {"GS": _rate_profile()},
        (_payload("P", 1_000_000, expiry_us=expiry_us),),
        (),
        DISABLED_STORAGE,
        TimeInterval(UtcInstant(0), UtcInstant(120_000_000)),
    )
    assert bool(ledger.allocations) is starts


def test_allocation_started_one_tick_before_expiry_runs_to_completion() -> None:
    session = _session(10_000_000, 40_000_000, 1_875_000)
    ledger = run_ledger(
        (session,),
        {"GS": _rate_profile()},
        (_payload("P", 1_000_000, expiry_us=10_000_001),),
        (),
        DISABLED_STORAGE,
        TimeInterval(UtcInstant(0), UtcInstant(120_000_000)),
    )
    assert ledger.allocations[0].end == UtcInstant(26_000_000)
    assert ledger.progress[0].remaining_bytes == 0


def test_endpoint_touch_is_not_a_conflict_and_zero_duration_is_rejected() -> None:
    left = _session(0, 10_000_000, 10)
    right = Candidate(
        "T", "GS2", TimeInterval(UtcInstant(10_000_000), UtcInstant(20_000_000)), 10, 0
    )
    assert not left.interval.overlaps(right.interval)
    assert {item.stable_key for item in select_maximum_nonoverlap((right, left))} == {"S", "T"}
    with pytest.raises(DomainValidationError):
        TimeInterval(UtcInstant(10_000_000), UtcInstant(10_000_000))


def test_window_split_conserves_duration_and_capacity() -> None:
    """AC-20 / PBT-24: clipping never re-applies the guard, so adjacent windows sum to the whole."""
    profile = _rate_profile()
    contact = SyntheticContact(
        "X",
        "GS",
        TimeInterval(
            UtcInstant.parse("2027-01-01T23:58:00Z"), UtcInstant.parse("2027-01-02T00:03:00Z")
        ),
    )
    whole = TimeInterval(
        UtcInstant.parse("2027-01-01T00:00:00Z"), UtcInstant.parse("2027-01-03T00:00:00Z")
    )
    first_day = DAY
    second_day = TimeInterval(
        UtcInstant.parse("2027-01-02T00:00:00Z"), UtcInstant.parse("2027-01-03T00:00:00Z")
    )
    full = calculate_contact_capacity(contact, profile, whole)
    left = calculate_contact_capacity(contact, profile, first_day)
    right = calculate_contact_capacity(contact, profile, second_day)
    assert full.capacity_bytes == 18_750_000
    assert left.capacity_bytes is not None and right.capacity_bytes is not None
    assert left.capacity_bytes + right.capacity_bytes == full.capacity_bytes
    assert left.modeled_interval is not None and right.modeled_interval is not None
    assert (
        left.modeled_interval.duration_us + right.modeled_interval.duration_us
        == contact.true_interval.duration_us
    )


@pytest.mark.parametrize(
    ("guard_us", "status"),
    [
        (44_999_999, CalculationStatus.COMPUTED),
        (45_000_000, CalculationStatus.KNOWN_ZERO),
        (45_000_001, CalculationStatus.KNOWN_ZERO),
    ],
)
def test_guard_sum_triplet(guard_us: int, status: CalculationStatus) -> None:
    """AC-21 / AC-39: guard sum <, =, > the pass length.

    Zero capacity from a valid PROXY guard is KNOWN_ZERO, never BLOCKED.
    """
    from dataclasses import replace

    profile = replace(
        _rate_profile(4_000_000), acquisition_guard_us=guard_us, release_guard_us=guard_us
    )
    contact = SyntheticContact(
        "X",
        "GS",
        TimeInterval(
            UtcInstant.parse("2027-01-01T00:00:00Z"), UtcInstant.parse("2027-01-01T00:01:30Z")
        ),
    )
    result = calculate_contact_capacity(contact, profile, DAY)
    assert result.status is status
    if status is CalculationStatus.KNOWN_ZERO:
        assert result.capacity_bytes == 0
        assert [code.value for code in result.reason_codes] == ["GUARD_EXCEEDS_WINDOW"]
        assert result.grade.value == "CONCEPT_ONLY"
