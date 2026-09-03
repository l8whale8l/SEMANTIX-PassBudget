"""Bounded-cost check for the reference P0 analysis size.

The non-functional target is one spacecraft, twenty ground stations and a seven-day window on an
ordinary CPU. The point of this test is not to publish a benchmark number - CI hardware varies -
but to fail loudly if the queue-aware search ever becomes exponential in the number of
non-conflicting opportunities again.
"""

from __future__ import annotations

import time
from dataclasses import replace

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.domain.enums import (
    AnalysisMode,
    CapacityProvider,
    DeadlineTarget,
    EvidenceState,
    PostDeadlineAction,
    SegmentationKind,
    ServiceClass,
)
from semantix_passbudget.domain.models import (
    CapacityProfile,
    Payload,
    ScenarioSnapshot,
    Station,
    SyntheticContact,
)
from semantix_passbudget.domain.time import TimeInterval, UtcInstant

STATIONS = 20
DAYS = 7
PASSES_PER_DAY = 5
PAYLOADS = 200
SECOND = 1_000_000

#: Generous upper bound: the reference target is 60 s for a far larger payload manifest.
WALL_CLOCK_BUDGET_S = 30.0


def _profile(capacity: int) -> CapacityProfile:
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
        source_revision_id="SCALE",
        rationale="Synthetic scale regression.",
    )


def _snapshot() -> ScenarioSnapshot:
    window = TimeInterval(UtcInstant(0), UtcInstant(DAYS * 86_400 * SECOND))
    stations = tuple(
        Station(f"GS-{index:02d}", index, _profile(20_000_000)) for index in range(STATIONS)
    )
    contacts: list[SyntheticContact] = []
    slot = 0
    for day in range(DAYS):
        for pass_index in range(PASSES_PER_DAY):
            for station in range(STATIONS):
                start = (day * 86_400 + pass_index * 17_280 + station * 600) * SECOND
                contacts.append(
                    SyntheticContact(
                        f"C{slot:05d}",
                        f"GS-{station:02d}",
                        TimeInterval(UtcInstant(start), UtcInstant(start + 480 * SECOND)),
                    )
                )
                slot += 1
    payloads = tuple(
        Payload(
            stable_key=f"P-{index:04d}",
            logical_size_bytes=5_000_000,
            storage_size_bytes=5_000_000,
            ready_at=UtcInstant(index * 600 * SECOND),
            service_class=ServiceClass.PRIORITY,
            deadline_at=UtcInstant((DAYS * 86_400 - 1) * SECOND),
            deadline_severity=0,
            mission_priority=index % 100,
            queue_sequence=index,
            segmentation=SegmentationKind.ATOMIC_OBJECT,
            chunk_size_bytes=None,
            resume_supported=False,
            deadline_target=DeadlineTarget.INSTANCE_COMPLETE,
            post_deadline_action=PostDeadlineAction.CONTINUE_AND_REPORT,
        )
        for index in range(PAYLOADS)
    )
    return ScenarioSnapshot(
        schema_version="passbudget-input-0.2",
        fixture_id="SCALE-REFERENCE",
        analysis_mode=AnalysisMode.QUEUE_AWARE,
        analysis_window=window,
        stations=stations,
        contacts=tuple(contacts),
        source_revision_id="SYN-CONTACT-SCALE-R1",
        safety_notice="Synthetic scale regression only.",
        decision_question="Does the reference analysis size stay within a bounded search cost?",
        policy_revision_id="DEADLINE_SEVERITY_CORE_V1",
        payloads=payloads,
    )


def test_reference_analysis_size_completes_within_a_bounded_time() -> None:
    snapshot = _snapshot()
    assert len(snapshot.contacts) == STATIONS * DAYS * PASSES_PER_DAY
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    started = time.perf_counter()
    run = service.run(snapshot)
    elapsed = time.perf_counter() - started
    assert run.status == "SUCCEEDED"
    metrics = run.result["metrics"]
    assert metrics["geometric_contact_count"] == STATIONS * DAYS * PASSES_PER_DAY
    assert metrics["scheduled_unique_capacity_bytes"] <= metrics["candidate_capacity_sum_bytes"]
    assert elapsed < WALL_CLOCK_BUDGET_S, f"reference analysis took {elapsed:.1f}s"


def test_pairwise_overlap_at_reference_size_still_searches_exactly() -> None:
    """Half the opportunities overlap a partner, so every conflict component needs a rollout."""
    base = _snapshot()
    shifted = tuple(
        SyntheticContact(
            contact.stable_key,
            contact.station_key,
            TimeInterval(
                UtcInstant(contact.true_interval.start.microseconds - 200 * SECOND),
                UtcInstant(contact.true_interval.end.microseconds - 200 * SECOND),
            ),
        )
        if index % 2
        else contact
        for index, contact in enumerate(base.contacts)
    )
    snapshot = replace(base, contacts=shifted)
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    started = time.perf_counter()
    run = service.run(snapshot)
    elapsed = time.perf_counter() - started
    assert run.status == "SUCCEEDED"
    assert run.result["metrics"]["suppressed_capacity_bytes"] > 0
    assert elapsed < WALL_CLOCK_BUDGET_S, f"overlapping reference analysis took {elapsed:.1f}s"
