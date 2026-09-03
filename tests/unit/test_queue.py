from __future__ import annotations

from semantix_passbudget.domain.enums import (
    AdmissionPolicy,
    CapacityProvider,
    DeliveryAssumption,
    EvidenceState,
    RateSemantics,
    ReclaimGranularity,
    ReleaseTrigger,
    ReserveEnforcement,
    SegmentationKind,
    ServiceClass,
    StorageMode,
)
from semantix_passbudget.domain.ledger import LedgerResult, run_ledger
from semantix_passbudget.domain.models import (
    DISABLED_STORAGE,
    CapacityProfile,
    ExactRate,
    Payload,
    RateSegment,
    StorageConfig,
)
from semantix_passbudget.domain.scheduler import Candidate
from semantix_passbudget.domain.time import TimeInterval, UtcInstant

WINDOW = TimeInterval(UtcInstant(0), UtcInstant(1_000_000_000))


def _payload(
    key: str,
    size: int,
    ready: int,
    segmentation: SegmentationKind,
    chunk: int | None = None,
) -> Payload:
    return Payload(
        stable_key=key,
        logical_size_bytes=size,
        storage_size_bytes=size,
        ready_at=UtcInstant(ready),
        service_class=ServiceClass.PRIORITY,
        deadline_at=None,
        deadline_severity=0,
        mission_priority=1,
        queue_sequence=1,
        segmentation=segmentation,
        chunk_size_bytes=chunk,
        resume_supported=segmentation is SegmentationKind.FIXED_CHUNK,
    )


def _fixed_profile(capacity: int) -> CapacityProfile:
    return CapacityProfile(
        provider=CapacityProvider.FIXED_CAPACITY_PER_CONTACT,
        rate_semantics=None,
        acquisition_guard_us=0,
        release_guard_us=0,
        rate_segments=(),
        fixed_capacity_bytes=capacity,
        byte_reserve=0,
        active_efficiency=None,
        rate_unknown=False,
        evidence_state=EvidenceState.PROXY,
        source_revision_id="TEST-R1",
        rationale="Synthetic unit test.",
    )


def _schedule(
    sessions: tuple[Candidate, ...],
    profiles: dict[str, CapacityProfile],
    payloads: tuple[Payload, ...],
    storage: StorageConfig = DISABLED_STORAGE,
) -> LedgerResult:
    return run_ledger(sessions, profiles, payloads, (), storage, WINDOW)


def test_atomic_object_never_starts_when_it_does_not_fit() -> None:
    session = Candidate("S", "GS", TimeInterval(UtcInstant(0), UtcInstant(10)), 5, 0)
    payload = _payload("P", 6, 0, SegmentationKind.ATOMIC_OBJECT)
    scheduled = _schedule((session,), {"GS": _fixed_profile(5)}, (payload,))
    assert scheduled.allocations == ()
    assert scheduled.progress[0].remaining_bytes == 6
    assert "NOT_STARTED_ATOMIC_NOT_COMPLETABLE" in {
        code.value for code in scheduled.progress[0].reason_codes
    }


def test_fixed_chunk_never_allocates_partial_chunk() -> None:
    session = Candidate("S", "GS", TimeInterval(UtcInstant(0), UtcInstant(10)), 55_500_000, 0)
    payload = _payload("P", 140_000_000, 0, SegmentationKind.FIXED_CHUNK, 1_000_000)
    scheduled = _schedule((session,), {"GS": _fixed_profile(55_500_000)}, (payload,))
    assert scheduled.allocations[0].allocated_bytes == 55_000_000
    assert scheduled.progress[0].remaining_bytes == 85_000_000
    assert scheduled.stranded_capacity_bytes == 500_000


def test_fixed_capacity_does_not_admit_payload_ready_mid_session() -> None:
    session = Candidate("S", "GS", TimeInterval(UtcInstant(0), UtcInstant(10)), 5, 0)
    payload = _payload("P", 5, 1, SegmentationKind.ATOMIC_OBJECT)
    scheduled = _schedule((session,), {"GS": _fixed_profile(5)}, (payload,))
    assert scheduled.allocations == ()


def test_soft_reserve_never_allows_physical_overflow() -> None:
    payload = _payload("P", 20_000_000, 0, SegmentationKind.ATOMIC_OBJECT)
    result = _schedule(
        (),
        {},
        (payload,),
        StorageConfig(
            mode=StorageMode.ENABLED,
            physical_capacity_bytes=200_000_000,
            reserve_bytes=0,
            initial_occupancy_bytes=190_000_000,
            reserve_enforcement=ReserveEnforcement.SOFT,
            admission_policy=AdmissionPolicy.REJECT_NEW,
            release_trigger=ReleaseTrigger.NEVER,
            delivery_assumption=DeliveryAssumption.NONE,
            reclaim_granularity=ReclaimGranularity.OBJECT,
        ),
    )
    assert result.storage.final_occupancy_bytes == 190_000_000
    assert result.storage.hard_overflow_bytes == 0
    assert result.storage.admissions[0].reason_code == "ADMISSION_REJECTED_PHYSICAL_LIMIT"


def test_fixed_rate_payload_can_start_at_ready_time_inside_session() -> None:
    session = Candidate(
        "S", "GS", TimeInterval(UtcInstant(0), UtcInstant(30_000_000)), 1_875_000, 0
    )
    profile = CapacityProfile(
        provider=CapacityProvider.FIXED_RATE,
        rate_semantics=RateSemantics.APPLICATION_GOODPUT,
        acquisition_guard_us=0,
        release_guard_us=0,
        rate_segments=(RateSegment(0, 0, 30_000_000, ExactRate(500_000, 1)),),
        fixed_capacity_bytes=None,
        byte_reserve=0,
        active_efficiency=None,
        rate_unknown=False,
        evidence_state=EvidenceState.PROXY,
        source_revision_id="AC-24",
        rationale="Synthetic mid-session ready-time regression.",
    )
    payload = _payload("P", 1_000_000, 10_000_000, SegmentationKind.ATOMIC_OBJECT)
    scheduled = _schedule((session,), {"GS": profile}, (payload,))
    assert scheduled.allocations[0].start == UtcInstant(10_000_000)
    assert scheduled.allocations[0].end == UtcInstant(26_000_000)


def test_fixed_capacity_commits_completion_at_session_end() -> None:
    """AC-P0-07 / AC-46: no in-pass rate evidence means no invented in-pass completion time."""
    session = Candidate(
        "S", "GS", TimeInterval(UtcInstant(0), UtcInstant(10_000_000)), 5_000_000, 0
    )
    payload = _payload("P", 1_000_000, 0, SegmentationKind.ATOMIC_OBJECT)
    scheduled = _schedule((session,), {"GS": _fixed_profile(5_000_000)}, (payload,))
    assert scheduled.allocations[0].end == session.interval.end
    assert scheduled.progress[0].modeled_tx_complete_at == session.interval.end
