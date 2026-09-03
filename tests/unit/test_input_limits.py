"""The P0 input ceilings, at the boundary and one past it.

`P0_FUNCTIONAL_SPEC.md` §15.4 requires them; `domain/limits.py` holds them; `validate()` applies
them. These cases pin three things:

* the boundary value is accepted, so a ceiling never quietly shrinks the supported scenario;
* one past the boundary is refused with `INPUT_LIMIT_EXCEEDED` and no partial analysis;
* an input-size refusal is not a branch-local calculation failure. The two produce different
  outcomes on purpose: a branch-local failure leaves a run whose successful branches are still
  readable (AC-P0-24), while an oversized input never becomes a run at all.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.domain import limits
from semantix_passbudget.domain.enums import (
    AdmissionPolicy,
    AnalysisMode,
    CapacityProvider,
    DeliveryAssumption,
    DependencyKind,
    EvidenceState,
    RateScope,
    RateSemantics,
    ReclaimGranularity,
    ReleaseTrigger,
    ReserveEnforcement,
    SegmentationKind,
    ServiceClass,
    StorageMode,
)
from semantix_passbudget.domain.errors import DomainValidationError
from semantix_passbudget.domain.models import (
    DISABLED_STORAGE,
    CapacityProfile,
    ExactRate,
    Payload,
    PayloadDependency,
    RateSegment,
    ScenarioSnapshot,
    Station,
    StorageConfig,
    SyntheticContact,
    SyntheticDeliveryEvent,
    TimeReserve,
)
from semantix_passbudget.domain.time import TimeInterval, UtcInstant
from semantix_passbudget.ports.run_repository import StoredRun

SECOND = 1_000_000
DAY = 86_400 * SECOND


def _fixed_capacity() -> CapacityProfile:
    return CapacityProfile(
        provider=CapacityProvider.FIXED_CAPACITY_PER_CONTACT,
        rate_semantics=None,
        acquisition_guard_us=0,
        release_guard_us=0,
        rate_segments=(),
        fixed_capacity_bytes=1_000_000,
        byte_reserve=0,
        active_efficiency=None,
        rate_unknown=False,
        evidence_state=EvidenceState.PROXY,
        source_revision_id="LIMITS",
        rationale="Synthetic input-ceiling regression.",
    )


def _rate_profile(segments: int, reserves: int) -> CapacityProfile:
    """A FIXED_RATE profile whose segment timeline is contiguous from zero, as validation wants."""
    span = 1 * SECOND
    return CapacityProfile(
        provider=CapacityProvider.FIXED_RATE,
        rate_semantics=RateSemantics.CODED_BITRATE,
        acquisition_guard_us=0,
        release_guard_us=0,
        rate_segments=tuple(
            RateSegment(index, index * span, (index + 1) * span, ExactRate(8_000_000, 1))
            for index in range(segments)
        ),
        fixed_capacity_bytes=None,
        byte_reserve=0,
        active_efficiency=Fraction(1, 1),
        rate_unknown=False,
        evidence_state=EvidenceState.PROXY,
        source_revision_id="LIMITS",
        rationale="Synthetic input-ceiling regression.",
        # Reserves must not overlap each other; they are packed after the rate timeline.
        time_reserves=tuple(
            TimeReserve(
                (segments + index) * span,
                (segments + index + 1) * span,
            )
            for index in range(reserves)
        ),
        measurement_point="SYNTHETIC_TEST_EGRESS",
        rate_scope=RateScope.ACTIVE_DATA_WINDOW,
    )


def _payload(index: int) -> Payload:
    return Payload(
        stable_key=f"P-{index:06d}",
        logical_size_bytes=1_000,
        storage_size_bytes=1_000,
        ready_at=UtcInstant(0),
        service_class=ServiceClass.BEST_EFFORT,
        deadline_at=None,
        deadline_severity=0,
        mission_priority=0,
        queue_sequence=index,
        segmentation=SegmentationKind.ATOMIC_OBJECT,
        chunk_size_bytes=None,
        resume_supported=False,
    )


def _forward_dependencies(payloads: int, wanted: int) -> tuple[PayloadDependency, ...]:
    """`wanted` distinct edges that always point forwards, so the graph cannot hold a cycle."""
    edges: list[PayloadDependency] = []
    stride = 1
    while len(edges) < wanted:
        if stride >= payloads:
            raise AssertionError(f"{payloads} payloads cannot carry {wanted} distinct edges")
        for index in range(payloads - stride):
            if len(edges) == wanted:
                break
            edges.append(
                PayloadDependency(
                    predecessor_key=f"P-{index:06d}",
                    successor_key=f"P-{index + stride:06d}",
                    kind=DependencyKind.SEND_AFTER,
                )
            )
        stride += 1
    return tuple(edges)


ACK_STORAGE = StorageConfig(
    mode=StorageMode.ENABLED,
    physical_capacity_bytes=200_000_000,
    reserve_bytes=0,
    initial_occupancy_bytes=0,
    reserve_enforcement=ReserveEnforcement.HARD,
    admission_policy=AdmissionPolicy.REJECT_NEW,
    release_trigger=ReleaseTrigger.ACKED,
    delivery_assumption=DeliveryAssumption.NONE,
    reclaim_granularity=ReclaimGranularity.OBJECT,
)


def _snapshot(
    *,
    window_us: int = DAY,
    stations: int = 1,
    contacts: int = 1,
    payloads: int = 0,
    dependencies: int = 0,
    delivery_events: int = 0,
    profile: CapacityProfile | None = None,
) -> ScenarioSnapshot:
    capacity = profile or _fixed_capacity()
    station_tuple = tuple(Station(f"GS-{index:04d}", index, capacity) for index in range(stations))
    contact_tuple = tuple(
        SyntheticContact(
            f"C-{index:06d}",
            station_tuple[index % stations].stable_key,
            TimeInterval(UtcInstant(index * 2 * SECOND), UtcInstant(index * 2 * SECOND + SECOND)),
        )
        for index in range(contacts)
    )
    queue_aware = payloads > 0
    return ScenarioSnapshot(
        schema_version="passbudget-input-0.2",
        fixture_id="LIMITS-REGRESSION",
        analysis_mode=AnalysisMode.QUEUE_AWARE if queue_aware else AnalysisMode.NETWORK_ONLY,
        analysis_window=TimeInterval(UtcInstant(0), UtcInstant(window_us)),
        stations=station_tuple,
        contacts=contact_tuple,
        source_revision_id="LIMITS-R1",
        safety_notice="Synthetic input-ceiling regression only.",
        decision_question="Is this input inside the P0 ceilings?",
        policy_revision_id="DEADLINE_SEVERITY_CORE_V1" if queue_aware else None,
        payloads=tuple(_payload(index) for index in range(payloads)),
        dependencies=_forward_dependencies(payloads, dependencies),
        storage=ACK_STORAGE if delivery_events else DISABLED_STORAGE,
        synthetic_delivery_events=tuple(
            # One event per payload: the domain requires each event to name a distinct payload.
            SyntheticDeliveryEvent(
                payload_key=f"P-{index:06d}",
                acknowledged_at=UtcInstant(index),
            )
            for index in range(delivery_events)
        ),
    )


class _RecordingRepository(InMemoryRunRepository):
    """An in-memory repository that also remembers whether anything was ever written."""

    def __init__(self) -> None:
        super().__init__()
        self.stored: list[str] = []

    def add(self, run: StoredRun) -> None:
        self.stored.append(run.run_id)
        super().add(run)


def _refusal(snapshot: ScenarioSnapshot) -> DomainValidationError:
    with pytest.raises(DomainValidationError) as caught:
        snapshot.validate()
    assert caught.value.detail.code == "INPUT_LIMIT_EXCEEDED"
    return caught.value


# --------------------------------------------------------------------------- boundary accepted


def test_the_specification_reference_scenario_is_inside_every_ceiling() -> None:
    """One spacecraft, 20 stations, a 7-day window and 10,000 payloads must remain legal."""
    _snapshot(window_us=7 * DAY, stations=20, contacts=700, payloads=limits.MAX_PAYLOADS).validate()


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("analysis window", {"window_us": limits.MAX_ANALYSIS_WINDOW_US}),
        ("stations", {"stations": limits.MAX_STATIONS, "contacts": limits.MAX_STATIONS}),
        ("contacts", {"contacts": limits.MAX_CONTACTS}),
        ("payloads", {"payloads": limits.MAX_PAYLOADS}),
    ],
)
def test_the_boundary_value_is_accepted(name: str, kwargs: dict[str, int]) -> None:
    _snapshot(**kwargs).validate()  # type: ignore[arg-type]


def test_the_segment_and_reserve_boundaries_are_accepted() -> None:
    _snapshot(
        profile=_rate_profile(
            limits.MAX_RATE_SEGMENTS_PER_STATION, limits.MAX_TIME_RESERVES_PER_STATION
        )
    ).validate()


# ----------------------------------------------------------------------------- one past refused


def test_an_over_long_analysis_window_is_refused() -> None:
    error = _refusal(_snapshot(window_us=limits.MAX_ANALYSIS_WINDOW_US + 1))
    assert error.detail.details["limit_name"] == "analysis window"
    assert error.detail.details["limit_maximum"] == str(limits.MAX_ANALYSIS_WINDOW_US)


def test_too_many_stations_are_refused() -> None:
    error = _refusal(_snapshot(stations=limits.MAX_STATIONS + 1, contacts=1))
    assert error.detail.details["limit_name"] == "station count"


def test_too_many_contacts_are_refused() -> None:
    error = _refusal(_snapshot(contacts=limits.MAX_CONTACTS + 1))
    assert error.detail.details["limit_name"] == "contact count"


def test_too_many_payloads_are_refused() -> None:
    error = _refusal(_snapshot(payloads=limits.MAX_PAYLOADS + 1))
    assert error.detail.details["limit_name"] == "payload count"


def test_too_many_rate_segments_for_one_station_are_refused() -> None:
    error = _refusal(_snapshot(profile=_rate_profile(limits.MAX_RATE_SEGMENTS_PER_STATION + 1, 0)))
    assert error.detail.details["limit_name"] == "rate segment count for one station"


def test_too_many_time_reserves_for_one_station_are_refused() -> None:
    error = _refusal(_snapshot(profile=_rate_profile(1, limits.MAX_TIME_RESERVES_PER_STATION + 1)))
    assert error.detail.details["limit_name"] == "time reserve count for one station"


def test_the_dependency_boundary_is_accepted() -> None:
    _snapshot(payloads=210, dependencies=limits.MAX_DEPENDENCIES).validate()


def test_too_many_dependencies_are_refused() -> None:
    error = _refusal(_snapshot(payloads=210, dependencies=limits.MAX_DEPENDENCIES + 1))
    assert error.detail.details["limit_name"] == "payload dependency count"


def test_the_synthetic_delivery_event_boundary_is_accepted() -> None:
    # Each event names a distinct payload, so the two ceilings meet here: 10,000 of each.
    events = limits.MAX_SYNTHETIC_DELIVERY_EVENTS
    _snapshot(payloads=events, delivery_events=events).validate()


def test_too_many_synthetic_delivery_events_are_refused() -> None:
    events = limits.MAX_SYNTHETIC_DELIVERY_EVENTS + 1
    error = _refusal(_snapshot(payloads=limits.MAX_PAYLOADS, delivery_events=events))
    assert error.detail.details["limit_name"] == "synthetic delivery event count"


def test_a_refusal_names_the_limit_without_echoing_the_input() -> None:
    error = _refusal(_snapshot(contacts=limits.MAX_CONTACTS + 1))
    rendered = repr(error.detail.as_dict())
    assert "LIMITS-REGRESSION" not in rendered
    assert "GS-0000" not in rendered
    assert "C-000000" not in rendered


# ------------------------------------------------------------------- not a branch-local failure


def test_an_oversized_input_never_becomes_a_run() -> None:
    """A ceiling refusal happens before any branch, so there is no PARTIAL run to inspect.

    AC-P0-24's branch-local failure is the opposite case: the run exists, is PARTIAL, and its
    successful branches stay readable. Conflating the two would let an oversized request consume
    the analysis it was refused for.
    """
    repository = _RecordingRepository()
    service = RunScenarioService(SyntheticContactProvider(), repository)
    with pytest.raises(DomainValidationError) as caught:
        service.run(_snapshot(contacts=limits.MAX_CONTACTS + 1))
    assert caught.value.detail.code == "INPUT_LIMIT_EXCEEDED"
    assert repository.stored == [], "a refused input must not reach persistence"


def test_every_ceiling_admits_the_reference_size_it_is_supposed_to_admit() -> None:
    """A ceiling below the specification's reference analysis would be a silent scope reduction."""
    assert limits.MAX_STATIONS >= 20
    assert limits.MAX_ANALYSIS_WINDOW_US >= 7 * DAY
    assert limits.MAX_CONTACTS >= 700
    assert limits.MAX_PAYLOADS >= 10_000
