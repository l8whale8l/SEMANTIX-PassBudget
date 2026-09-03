"""`EXACT_GLOBAL` and `BOUNDED_APPROXIMATE`: two modes that must never be confused for each other.

The PM decision is that a bounded approximation exists, that it is chosen deliberately, and that
its results are never dressed up as optimal. Three properties carry that decision, and each is
asserted here rather than assumed:

* exact is the default, and an exact search that runs out of budget **fails** -- it does not
  quietly become the approximation;
* the approximation is feasible and deterministic, and never scores better than the exact
  optimum on the same instance;
* the grade travels with the result, so nobody can read an approximate number as an exact one.

The strategy is a semantic input, so it also changes the canonical input hash: two runs that
differ only in strategy are two different questions, not two answers to one.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations as subsets

import pytest

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.comparison import compare_results
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.domain import horizon
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
from semantix_passbudget.domain.horizon import (
    APPROXIMATE_OBJECTIVE_REVISION,
    EXACT_WORK_BUDGET,
    GLOBAL_COMBINATION_BUDGET,
    evaluate_objective,
    select_queue_aware_nonoverlap,
)
from semantix_passbudget.domain.ledger import run_ledger
from semantix_passbudget.domain.models import (
    DISABLED_STORAGE,
    CapacityProfile,
    Payload,
    ScenarioSnapshot,
    Station,
    SyntheticContact,
)
from semantix_passbudget.domain.scheduler import Candidate
from semantix_passbudget.domain.time import TimeInterval, UtcInstant

SECOND = 1_000_000
MB = 1_000_000
WINDOW = TimeInterval(UtcInstant(0), UtcInstant(600 * SECOND))


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
        source_revision_id="STRATEGY",
        rationale="Synthetic execution-strategy regression.",
    )


def _candidate(key: str, start_s: int, end_s: int, capacity: int) -> Candidate:
    return Candidate(
        key,
        key,
        TimeInterval(UtcInstant(start_s * SECOND), UtcInstant(end_s * SECOND)),
        capacity,
        0,
    )


def _payload(
    key: str,
    size: int,
    sequence: int,
    deadline_s: int | None = None,
    *,
    service_class: ServiceClass = ServiceClass.MANDATORY,
    ready_s: int = 0,
) -> Payload:
    return Payload(
        stable_key=key,
        logical_size_bytes=size,
        storage_size_bytes=size,
        ready_at=UtcInstant(ready_s * SECOND),
        service_class=service_class,
        deadline_at=None if deadline_s is None else UtcInstant(deadline_s * SECOND),
        deadline_severity=0,
        mission_priority=100 - sequence,
        queue_sequence=sequence,
        segmentation=SegmentationKind.ATOMIC_OBJECT,
        chunk_size_bytes=None,
        resume_supported=False,
        deadline_target=None if deadline_s is None else DeadlineTarget.INSTANCE_COMPLETE,
        post_deadline_action=(
            None if deadline_s is None else PostDeadlineAction.CONTINUE_AND_REPORT
        ),
    )


#: One component where the three policies genuinely disagree (A is bigger, B finishes sooner),
#: and one component with nothing to choose.
DISAGREEING = (
    _candidate("A", 0, 10, 10 * MB),
    _candidate("B", 0, 3, 1 * MB),
    _candidate("C", 100, 110, 4 * MB),
)
DISAGREEING_PROFILES = {item.station_key: _profile(item.capacity_bytes) for item in DISAGREEING}
DISAGREEING_PAYLOADS = (
    _payload("M", 1 * MB, 1, 5, ready_s=0),
    _payload("P", 10 * MB, 2, None, service_class=ServiceClass.PRIORITY),
)


def _select(candidates: tuple[Candidate, ...], strategy: ExecutionStrategy) -> object:
    return select_queue_aware_nonoverlap(
        candidates,
        DISAGREEING_PROFILES,
        DISAGREEING_PAYLOADS,
        (),
        DISABLED_STORAGE,
        WINDOW,
        (),
        strategy,
    )


def _objective(sessions: tuple[Candidate, ...]) -> tuple[object, ...]:
    ledger = run_ledger(
        sessions, DISAGREEING_PROFILES, DISAGREEING_PAYLOADS, (), DISABLED_STORAGE, WINDOW
    )
    return evaluate_objective(ledger, DISAGREEING_PAYLOADS, sessions, WINDOW).as_key()


# ------------------------------------------------------------------------------ the two grades


def test_exact_is_the_default_everywhere() -> None:
    assert _snapshot().execution_strategy is ExecutionStrategy.EXACT_GLOBAL
    outcome = select_queue_aware_nonoverlap(
        DISAGREEING, DISAGREEING_PROFILES, DISAGREEING_PAYLOADS, (), DISABLED_STORAGE, WINDOW
    )
    assert outcome.status.value == "EXACT"


def test_exact_reports_what_it_established() -> None:
    outcome = _select(DISAGREEING, ExecutionStrategy.EXACT_GLOBAL)
    assert outcome.status.value == "EXACT"  # type: ignore[attr-defined]
    assert outcome.globally_optimal is True  # type: ignore[attr-defined]
    assert outcome.algorithm_revision.startswith("QUEUE_AWARE_LEXICOGRAPHIC")  # type: ignore[attr-defined]


def test_approximate_never_claims_optimality() -> None:
    outcome = _select(DISAGREEING, ExecutionStrategy.BOUNDED_APPROXIMATE)
    assert outcome.status.value == "APPROXIMATE"  # type: ignore[attr-defined]
    assert outcome.globally_optimal is False  # type: ignore[attr-defined]
    assert outcome.optimality_gap is None  # type: ignore[attr-defined]
    assert outcome.algorithm_revision == APPROXIMATE_OBJECTIVE_REVISION  # type: ignore[attr-defined]


def test_approximate_is_feasible_and_deterministic() -> None:
    outcome = _select(DISAGREEING, ExecutionStrategy.BOUNDED_APPROXIMATE)
    sessions = outcome.sessions  # type: ignore[attr-defined]
    assert {item.stable_key for item in sessions} <= {item.stable_key for item in DISAGREEING}
    for left, right in subsets(sessions, 2):
        assert not left.interval.overlaps(right.interval), "the selection must be schedulable"
    for order in ((2, 0, 1), (1, 2, 0), (0, 2, 1)):
        permuted = _select(
            tuple(DISAGREEING[index] for index in order), ExecutionStrategy.BOUNDED_APPROXIMATE
        )
        assert [item.stable_key for item in permuted.sessions] == [  # type: ignore[attr-defined]
            item.stable_key for item in sessions
        ]


def test_approximate_never_scores_better_than_the_exhaustive_optimum() -> None:
    """The known quality difference, stated as an inequality rather than assumed away."""
    approximate = _select(DISAGREEING, ExecutionStrategy.BOUNDED_APPROXIMATE)
    best = max(
        (
            _objective(subset)
            for size in range(len(DISAGREEING) + 1)
            for subset in subsets(DISAGREEING, size)
            if not any(left.interval.overlaps(right.interval) for left, right in subsets(subset, 2))
        ),
    )
    assert _objective(approximate.sessions) <= best  # type: ignore[attr-defined]
    exact = _select(DISAGREEING, ExecutionStrategy.EXACT_GLOBAL)
    assert _objective(exact.sessions) == best  # type: ignore[attr-defined]


# ------------------------------------------------------------------------- no automatic fallback


def _many_conflicts(components: int) -> tuple[Candidate, ...]:
    """`components` two-way conflicts, spaced so they never merge into one component."""
    return tuple(
        _candidate(f"S{index:02d}{side}", index * 20 + offset, index * 20 + offset + 6, 1 * MB)
        for index in range(components)
        for side, offset in (("A", 0), ("B", 3))
    )


def test_an_exact_search_over_the_combination_budget_fails_rather_than_approximating() -> None:
    candidates = _many_conflicts(13)  # 2**13 = 8192 combinations
    profiles = {item.station_key: _profile(item.capacity_bytes) for item in candidates}
    with pytest.raises(DomainValidationError) as caught:
        select_queue_aware_nonoverlap(
            candidates,
            profiles,
            DISAGREEING_PAYLOADS,
            (),
            DISABLED_STORAGE,
            WINDOW,
            (),
            ExecutionStrategy.EXACT_GLOBAL,
        )
    assert caught.value.detail.code == "QUEUE_HORIZON_GLOBAL_SEARCH_BUDGET_EXCEEDED"


def test_an_exact_search_inside_the_combination_budget_can_still_be_too_much_work() -> None:
    """The combination count says nothing about cost: one combination is one whole-horizon pass."""
    candidates = _many_conflicts(12)  # 2**12 = 4096, exactly the combination budget
    profiles = {item.station_key: _profile(item.capacity_bytes) for item in candidates}
    payloads = tuple(_payload(f"P{index:03d}", 1 * MB, index) for index in range(100))
    scale = len(candidates) // 2 + len(payloads)
    assert GLOBAL_COMBINATION_BUDGET * scale > EXACT_WORK_BUDGET, "the instance must be over"
    with pytest.raises(DomainValidationError) as caught:
        select_queue_aware_nonoverlap(
            candidates,
            profiles,
            payloads,
            (),
            DISABLED_STORAGE,
            WINDOW,
            (),
            ExecutionStrategy.EXACT_GLOBAL,
        )
    assert caught.value.detail.code == "QUEUE_HORIZON_EXACT_WORK_BUDGET_EXCEEDED"
    assert "on your behalf" in caught.value.detail.message


def test_the_same_instance_is_answered_when_approximation_is_chosen_deliberately() -> None:
    candidates = _many_conflicts(12)
    profiles = {item.station_key: _profile(item.capacity_bytes) for item in candidates}
    payloads = tuple(_payload(f"P{index:03d}", 1 * MB, index) for index in range(100))
    outcome = select_queue_aware_nonoverlap(
        candidates,
        profiles,
        payloads,
        (),
        DISABLED_STORAGE,
        WINDOW,
        (),
        ExecutionStrategy.BOUNDED_APPROXIMATE,
    )
    assert outcome.status.value == "APPROXIMATE"
    assert len(outcome.sessions) == 12


# ------------------------------------------------------------------------------- the run result


def _snapshot(
    strategy: ExecutionStrategy = ExecutionStrategy.EXACT_GLOBAL,
    mode: AnalysisMode = AnalysisMode.QUEUE_AWARE,
) -> ScenarioSnapshot:
    stations = tuple(
        Station(item.station_key, 0, _profile(item.capacity_bytes)) for item in DISAGREEING
    )
    contacts = tuple(
        SyntheticContact(f"c/{item.stable_key}", item.station_key, item.interval)
        for item in DISAGREEING
    )
    queue = mode is AnalysisMode.QUEUE_AWARE
    return ScenarioSnapshot(
        schema_version="passbudget-input-0.2",
        fixture_id="STRATEGY-REGRESSION",
        analysis_mode=mode,
        analysis_window=WINDOW,
        stations=stations,
        contacts=contacts,
        source_revision_id="STRATEGY-R1",
        safety_notice="Synthetic execution-strategy regression only.",
        decision_question="Which execution strategy answered this?",
        policy_revision_id="DEADLINE_SEVERITY_CORE_V1" if queue else None,
        payloads=DISAGREEING_PAYLOADS if queue else (),
        execution_strategy=strategy,
    )


def _run(strategy: ExecutionStrategy) -> object:
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    return service.run(_snapshot(strategy))


def test_the_result_carries_the_grade_and_the_warning() -> None:
    approximate = _run(ExecutionStrategy.BOUNDED_APPROXIMATE)
    block = approximate.result["optimization"]  # type: ignore[attr-defined]
    assert block == {
        "execution_strategy": "BOUNDED_APPROXIMATE",
        "optimization_status": "APPROXIMATE",
        "globally_optimal": False,
        "optimality_gap": None,
        "algorithm_revision": APPROXIMATE_OBJECTIVE_REVISION,
    }
    codes = {item["code"] for item in approximate.result["warnings"]}  # type: ignore[attr-defined]
    assert "NOT_GLOBALLY_OPTIMAL" in codes

    exact = _run(ExecutionStrategy.EXACT_GLOBAL)
    exact_block = exact.result["optimization"]  # type: ignore[attr-defined]
    assert exact_block["optimization_status"] == "EXACT"
    assert exact_block["globally_optimal"] is True
    exact_codes = {item["code"] for item in exact.result["warnings"]}  # type: ignore[attr-defined]
    assert "NOT_GLOBALLY_OPTIMAL" not in exact_codes


def test_the_strategy_is_a_semantic_input_and_changes_every_hash() -> None:
    exact = _run(ExecutionStrategy.EXACT_GLOBAL)
    approximate = _run(ExecutionStrategy.BOUNDED_APPROXIMATE)
    assert exact.input_snapshot_hash != approximate.input_snapshot_hash  # type: ignore[attr-defined]
    assert exact.result_content_hash != approximate.result_content_hash  # type: ignore[attr-defined]
    assert exact.run_record_hash != approximate.run_record_hash  # type: ignore[attr-defined]
    assert (
        exact.input_snapshot_payload["execution_strategy"] == "EXACT_GLOBAL"  # type: ignore[attr-defined]
    )


def test_the_engine_manifest_names_both_algorithms() -> None:
    manifest = _run(ExecutionStrategy.EXACT_GLOBAL).result["engine_manifest"]  # type: ignore[attr-defined]
    assert manifest["overlap_objective_revision"].startswith("QUEUE_AWARE_LEXICOGRAPHIC")
    assert manifest["approximate_objective_revision"] == APPROXIMATE_OBJECTIVE_REVISION


def test_network_only_refuses_a_strategy_it_cannot_honour() -> None:
    snapshot = _snapshot(ExecutionStrategy.BOUNDED_APPROXIMATE, AnalysisMode.NETWORK_ONLY)
    with pytest.raises(DomainValidationError) as caught:
        snapshot.validate()
    assert caught.value.detail.code == "EXECUTION_STRATEGY_NOT_APPLICABLE"


def test_network_only_reports_the_exact_grade_it_actually_has() -> None:
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    run = service.run(_snapshot(ExecutionStrategy.EXACT_GLOBAL, AnalysisMode.NETWORK_ONLY))
    assert run.result["optimization"]["optimization_status"] == "EXACT"
    assert run.result["optimization"]["algorithm_revision"] == "NETWORK_ONLY_MAX_CAPACITY_DP_V1"


def test_comparing_an_exact_run_against_an_approximate_one_warns() -> None:
    exact = _run(ExecutionStrategy.EXACT_GLOBAL)
    approximate = _run(ExecutionStrategy.BOUNDED_APPROXIMATE)
    comparison = compare_results(exact.result, approximate.result)  # type: ignore[attr-defined]
    warning = next(
        item for item in comparison["warnings"] if item["code"] == "OPTIMIZATION_GRADE_MISMATCH"
    )
    assert warning["baseline_optimization_status"] == "EXACT"
    assert warning["candidate_optimization_status"] == "APPROXIMATE"
    assert comparison["candidate_optimization"]["globally_optimal"] is False


def test_comparing_two_runs_of_the_same_grade_does_not_warn() -> None:
    left = _run(ExecutionStrategy.EXACT_GLOBAL)
    right = _run(ExecutionStrategy.EXACT_GLOBAL)
    comparison = compare_results(left.result, right.result)  # type: ignore[attr-defined]
    assert not [
        item for item in comparison["warnings"] if item["code"] == "OPTIMIZATION_GRADE_MISMATCH"
    ]


def test_the_strategy_survives_a_persistence_round_trip() -> None:
    repository = InMemoryRunRepository()
    service = RunScenarioService(SyntheticContactProvider(), repository)
    stored = service.run(_snapshot(ExecutionStrategy.BOUNDED_APPROXIMATE))
    loaded = repository.get(stored.run_id)
    assert loaded is not None
    assert loaded.input_snapshot_payload["execution_strategy"] == "BOUNDED_APPROXIMATE"
    assert loaded.result["optimization"]["optimization_status"] == "APPROXIMATE"
    assert loaded.input_snapshot_hash == stored.input_snapshot_hash
    assert loaded.result_content_hash == stored.result_content_hash


def test_a_replaced_strategy_is_the_only_difference_between_the_two_runs() -> None:
    """Two questions, not two answers: everything else about the input is identical."""
    base = _snapshot(ExecutionStrategy.EXACT_GLOBAL)
    other = replace(base, execution_strategy=ExecutionStrategy.BOUNDED_APPROXIMATE)
    assert base.contacts == other.contacts
    assert base.payloads == other.payloads
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    assert service.validate(base) != service.validate(other)


# ------------------------------------------------- one component, more maximal sets than exact


def _one_dense_component() -> tuple[Candidate, ...]:
    """Twelve separated two-way conflicts, plus one contact that overlaps every one of them.

    The spanner welds the twelve conflicts into a single connected component, so the component
    holds 2**12 + 1 maximal non-overlapping sets -- one past `MAXIMAL_SET_BUDGET`. The exact
    search must refuse it. The bounded approximation must not even look at that number: it is a
    property of the exact search's candidate generation, not of the instance.
    """
    pairs = tuple(
        _candidate(f"P{index:02d}{side}", index * 20 + offset, index * 20 + offset + 6, 5 * MB)
        for index in range(12)
        for side, offset in (("A", 0), ("B", 3))
    )
    return (*pairs, _candidate("LONG", 0, 12 * 20, 30 * MB))


DENSE_COMPONENT = _one_dense_component()
DENSE_PROFILES = {item.station_key: _profile(item.capacity_bytes) for item in DENSE_COMPONENT}
DENSE_WINDOW = TimeInterval(UtcInstant(0), UtcInstant(400 * SECOND))


def _select_dense(strategy: ExecutionStrategy) -> object:
    return select_queue_aware_nonoverlap(
        DENSE_COMPONENT,
        DENSE_PROFILES,
        DISAGREEING_PAYLOADS,
        (),
        DISABLED_STORAGE,
        DENSE_WINDOW,
        (),
        strategy,
    )


def test_the_dense_component_is_one_component_past_the_maximal_set_budget() -> None:
    assert len(DENSE_COMPONENT) == 25
    assert len(horizon.conflict_components(DENSE_COMPONENT)) == 1
    with pytest.raises(DomainValidationError) as caught:
        horizon.maximal_nonoverlapping_sets(DENSE_COMPONENT)
    assert caught.value.detail.code == "QUEUE_HORIZON_SEARCH_BUDGET_EXCEEDED"


def test_exact_refuses_the_dense_component() -> None:
    with pytest.raises(DomainValidationError) as caught:
        _select_dense(ExecutionStrategy.EXACT_GLOBAL)
    assert caught.value.detail.code == "QUEUE_HORIZON_SEARCH_BUDGET_EXCEEDED"


def test_the_approximation_answers_the_dense_component_the_exact_search_refuses() -> None:
    """Regression: this used to fail with the exact search's own budget error.

    `select_queue_aware_nonoverlap` partitioned into conflict components -- which enumerates
    maximal sets -- *before* it looked at the strategy, so the approximation inherited a limit
    that has nothing to do with it.
    """
    outcome = _select_dense(ExecutionStrategy.BOUNDED_APPROXIMATE)
    assert outcome.status.value == "APPROXIMATE"  # type: ignore[attr-defined]
    assert outcome.globally_optimal is False  # type: ignore[attr-defined]
    sessions = outcome.sessions  # type: ignore[attr-defined]
    assert sessions, "the approximation must return a selection, not an empty one"
    assert {item.stable_key for item in sessions} <= {item.stable_key for item in DENSE_COMPONENT}
    for left, right in subsets(sessions, 2):
        assert not left.interval.overlaps(right.interval)


def test_the_dense_component_selection_is_independent_of_input_order() -> None:
    reference = _select_dense(ExecutionStrategy.BOUNDED_APPROXIMATE).sessions  # type: ignore[attr-defined]
    reversed_input = select_queue_aware_nonoverlap(
        tuple(reversed(DENSE_COMPONENT)),
        DENSE_PROFILES,
        DISAGREEING_PAYLOADS,
        (),
        DISABLED_STORAGE,
        DENSE_WINDOW,
        (),
        ExecutionStrategy.BOUNDED_APPROXIMATE,
    ).sessions
    rotated = select_queue_aware_nonoverlap(
        (*DENSE_COMPONENT[7:], *DENSE_COMPONENT[:7]),
        DENSE_PROFILES,
        DISAGREEING_PAYLOADS,
        (),
        DISABLED_STORAGE,
        DENSE_WINDOW,
        (),
        ExecutionStrategy.BOUNDED_APPROXIMATE,
    ).sessions
    keys = [item.stable_key for item in reference]
    assert [item.stable_key for item in reversed_input] == keys
    assert [item.stable_key for item in rotated] == keys


def test_the_approximation_never_walks_the_exact_search_candidate_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two modes must not share a candidate generator, so neither can inherit the other's
    limits. Asserted structurally rather than by hoping the error codes never appear."""

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the bounded approximation reached exact candidate generation")

    monkeypatch.setattr(horizon, "_partition", forbidden)
    monkeypatch.setattr(horizon, "maximal_nonoverlapping_sets", forbidden)
    monkeypatch.setattr(horizon, "conflict_components", forbidden)
    outcome = _select_dense(ExecutionStrategy.BOUNDED_APPROXIMATE)
    assert outcome.status.value == "APPROXIMATE"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "candidates",
    [DENSE_COMPONENT, _many_conflicts(20)],
    ids=["one-dense-component", "twenty-separate-conflicts"],
)
def test_no_exact_only_error_can_come_out_of_the_bounded_mode(
    candidates: tuple[Candidate, ...],
) -> None:
    exact_only = {
        "QUEUE_HORIZON_SEARCH_BUDGET_EXCEEDED",
        "QUEUE_HORIZON_GLOBAL_SEARCH_BUDGET_EXCEEDED",
        "QUEUE_HORIZON_EXACT_WORK_BUDGET_EXCEEDED",
    }
    profiles = {item.station_key: _profile(item.capacity_bytes) for item in candidates}
    try:
        outcome = select_queue_aware_nonoverlap(
            candidates,
            profiles,
            DISAGREEING_PAYLOADS,
            (),
            DISABLED_STORAGE,
            DENSE_WINDOW,
            (),
            ExecutionStrategy.BOUNDED_APPROXIMATE,
        )
    except DomainValidationError as error:  # pragma: no cover - the assertion is the point
        assert error.detail.code not in exact_only, f"exact-only error {error.detail.code}"
        raise
    assert outcome.status.value == "APPROXIMATE"
