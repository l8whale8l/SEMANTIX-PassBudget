"""Bounded-cost check for the reference P0 analysis size.

The non-functional target is one spacecraft, twenty ground stations and a seven-day window on an
ordinary CPU. The point of this test is not to publish a benchmark number - CI hardware varies -
but to fail loudly if the queue-aware search ever becomes exponential in the number of
non-conflicting opportunities again.
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace

import pytest

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.domain.enums import (
    AnalysisMode,
    CapacityProvider,
    DeadlineTarget,
    EvidenceState,
    ExecutionStrategy,
    PostDeadlineAction,
    SegmentationKind,
    ServiceClass,
)
from semantix_passbudget.domain.errors import DomainValidationError
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
PAYLOADS = 10_000
SECOND = 1_000_000

#: The specification's own non-functional target (P0_FUNCTIONAL_SPEC.md §15.2) for the reference
#: analysis size, used verbatim rather than relaxed. Measured headroom is recorded in
#: docs/specs/P0_ACCEPTANCE_MATRIX.md; the point of the assertion is to fail if the search ever
#: becomes exponential again, not to publish a benchmark number.
WALL_CLOCK_BUDGET_S = 60.0


def _wall_clock_is_measurable() -> bool:
    """Whether a stopwatch reading means anything in this process.

    Coverage and profilers inflate wall clock several-fold, so under them the budget below
    reports the tracer rather than the algorithm. The exactness assertions still run either
    way; only the stopwatch is dropped, and the plain `pytest` that CI runs keeps the guard.
    """
    if sys.gettrace() is not None or sys.getprofile() is not None:
        return False
    try:
        import coverage
    except ModuleNotFoundError:
        return True
    return coverage.Coverage.current() is None


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
            stable_key=f"P-{index:05d}",
            logical_size_bytes=5_000_000,
            storage_size_bytes=5_000_000,
            ready_at=UtcInstant((index * DAYS * 86_400 * SECOND) // PAYLOADS),
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
    if _wall_clock_is_measurable():
        assert elapsed < WALL_CLOCK_BUDGET_S, f"reference analysis took {elapsed:.1f}s"


def _with_shifted_contacts(indices: frozenset[int]) -> ScenarioSnapshot:
    """The reference scenario with the named contacts pulled 200 s earlier, so each overlaps its
    neighbour and turns one conflict component into a genuine two-way alternative."""
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
        if index in indices
        else contact
        for index, contact in enumerate(base.contacts)
    )
    return replace(base, contacts=shifted)


def test_a_few_overlaps_at_reference_size_are_still_searched_globally() -> None:
    """Two real conflicts at reference size: four whole-horizon rollouts, not an estimate.

    Each combination costs one full `run_ledger` over 700 contacts and 10,000 payloads, so this
    also pins the cost model that `GLOBAL_COMBINATION_BUDGET` does *not* bound: the budget limits
    the number of combinations, and wall clock is that number times the instance size.
    """
    snapshot = _with_shifted_contacts(frozenset({11, 23}))
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    started = time.perf_counter()
    run = service.run(snapshot)
    elapsed = time.perf_counter() - started
    assert run.status == "SUCCEEDED"
    assert run.result["metrics"]["suppressed_capacity_bytes"] > 0
    if _wall_clock_is_measurable():
        assert elapsed < WALL_CLOCK_BUDGET_S, f"two-conflict reference analysis took {elapsed:.1f}s"


def test_dense_pairwise_overlap_is_refused_rather_than_approximated() -> None:
    """Half the opportunities overlap a partner, which is past what exact global search can do.

    Every such pair is an independent two-way choice and the objective is global, so the search
    space is 2**350. The selection is refused with a named budget code. It is *not* answered by
    committing component by component against a byte-maximising estimate of the future: that is
    what `QUEUE_AWARE_LEXICOGRAPHIC_HORIZON_V2` did, and
    `tests/unit/test_horizon.py::test_cross_component_alternatives_are_evaluated_against_the_whole_horizon`
    is the two-component instance where it returns the wrong answer.
    """
    snapshot = _with_shifted_contacts(
        frozenset(index for index in range(len(_snapshot().contacts)) if index % 2)
    )
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    with pytest.raises(DomainValidationError) as caught:
        service.run(snapshot)
    assert caught.value.detail.code == "QUEUE_HORIZON_GLOBAL_SEARCH_BUDGET_EXCEEDED"
    # The refusal names the limit, never a partial or byte-only answer.
    assert "approximated" in caught.value.detail.message


def test_the_dense_fixture_the_exact_search_refuses_is_answered_by_the_bounded_mode() -> None:
    """The same input the exact mode will not touch, answered inside the performance target.

    This is the whole point of `BOUNDED_APPROXIMATE` existing: 20 stations, 7 days, 700 contacts,
    10,000 payloads and 350 genuine two-way conflicts. The exact search would need 2**350
    whole-horizon rollouts and refuses; the bounded family costs at most one rollout per policy.
    The result is feasible and says plainly that it is not proven optimal.
    """
    dense = replace(
        _with_shifted_contacts(
            frozenset(index for index in range(len(_snapshot().contacts)) if index % 2)
        ),
        execution_strategy=ExecutionStrategy.BOUNDED_APPROXIMATE,
    )
    assert len(dense.contacts) == STATIONS * DAYS * PASSES_PER_DAY
    assert len(dense.payloads) == PAYLOADS == 10_000
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    started = time.perf_counter()
    run = service.run(dense)
    elapsed = time.perf_counter() - started

    assert run.status == "SUCCEEDED"
    assert run.result["optimization"] == {
        "execution_strategy": "BOUNDED_APPROXIMATE",
        "optimization_status": "APPROXIMATE",
        "globally_optimal": False,
        "optimality_gap": None,
        "algorithm_revision": "QUEUE_AWARE_BOUNDED_POLICY_FAMILY_V2",
    }
    assert "NOT_GLOBALLY_OPTIMAL" in {item["code"] for item in run.result["warnings"]}
    assert run.result["metrics"]["scheduled_unique_capacity_bytes"] > 0
    if _wall_clock_is_measurable():
        assert elapsed < WALL_CLOCK_BUDGET_S, f"dense approximate analysis took {elapsed:.1f}s"


def _one_connected_component() -> ScenarioSnapshot:
    """The reference contact count welded into a single conflict component.

    Each contact overlaps its neighbour and nothing else, so the overlap graph is one path of 700
    nodes. Its maximal non-overlapping sets are Fibonacci-many, which the exact search refuses
    outright -- and which the bounded mode must never compute in the first place.
    """
    base = _snapshot()
    contacts = tuple(
        SyntheticContact(
            f"C{index:05d}",
            base.stations[index % STATIONS].stable_key,
            TimeInterval(
                UtcInstant(index * 600 * SECOND),
                UtcInstant((index * 600 + 900) * SECOND),
            ),
        )
        for index in range(STATIONS * DAYS * PASSES_PER_DAY)
    )
    return replace(base, contacts=contacts)


def test_a_single_connected_component_at_reference_size_is_refused_by_the_exact_search() -> None:
    snapshot = replace(
        _one_connected_component(), execution_strategy=ExecutionStrategy.EXACT_GLOBAL
    )
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    with pytest.raises(DomainValidationError) as caught:
        service.run(snapshot)
    assert caught.value.detail.code == "QUEUE_HORIZON_SEARCH_BUDGET_EXCEEDED"


def test_a_single_connected_component_at_reference_size_is_answered_by_the_bounded_mode() -> None:
    """Performance regression for the mode's whole reason to exist.

    700 contacts in one component and 10,000 payloads. The bounded mode does no component
    decomposition and no maximal-set enumeration, so its cost is three polynomial schedules plus
    at most three rollouts -- independent of how densely the component is connected.
    """
    snapshot = replace(
        _one_connected_component(), execution_strategy=ExecutionStrategy.BOUNDED_APPROXIMATE
    )
    assert len(snapshot.contacts) == STATIONS * DAYS * PASSES_PER_DAY
    assert len(snapshot.payloads) == PAYLOADS == 10_000
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    started = time.perf_counter()
    run = service.run(snapshot)
    elapsed = time.perf_counter() - started

    assert run.status == "SUCCEEDED"
    assert run.result["optimization"]["optimization_status"] == "APPROXIMATE"
    assert run.result["metrics"]["scheduled_session_count"] > 0
    if _wall_clock_is_measurable():
        assert elapsed < WALL_CLOCK_BUDGET_S, f"single-component approximate took {elapsed:.1f}s"
