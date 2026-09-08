"""Metamorphic properties of the horizon-aware selection.

These are *not* an independent oracle for the objective's value. They check the structural
claims the implementation makes on top of the objective, using an independently written
brute-force search over every pairwise non-overlapping subset:

* `SESSION_ADDITION_MONOTONICITY_V1` — restricting the search to maximal non-overlapping sets
  never loses the best selection;
* **global** optimality across conflict components — enumerating every combination of the
  branching components' alternatives and scoring each with one whole-horizon rollout reaches the
  same selection as searching all subsets at once. This is the claim
  `QUEUE_AWARE_LEXICOGRAPHIC_HORIZON_V3` makes and `..._V2` did not: V2 committed component by
  component against a byte-maximising estimate of the future;
* determinism — the same input in a different order produces the same selection, and a complete
  tie is broken by the documented profile rather than by enumeration order;
* the bounded approximation's contract — feasible, deterministic, and never scoring better than
  the exhaustive optimum. It is allowed to score worse; that is what makes it an approximation,
  and the inequality is the only thing that may be relied on.

The generated instances deliberately carry at least two conflict components, a MANDATORY and
PRIORITY mix, different `ready_at` values, different payload sizes and a mix of deadlined and
undeadlined payloads. Every one of those is needed to separate a global search from a
component-local one; the two-component counterexample in `tests/unit/test_horizon.py` is the
fixed instance of the same shape.

**What is not claimed:** these instances are small enough to enumerate exhaustively (at most six
candidates). They say nothing about whether the global search stays affordable, which
`GLOBAL_COMBINATION_BUDGET` bounds explicitly and `tests/unit/test_scalability.py` exercises at
the reference analysis size.

The brute-force search here enumerates subsets itself and shares only the objective evaluation, so
a bug in component decomposition, maximality pruning, cross-component combination or tie-breaking
is visible.
"""

from __future__ import annotations

from itertools import combinations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from semantix_passbudget.domain.enums import (
    CapacityProvider,
    EvidenceState,
    ExecutionStrategy,
    SegmentationKind,
    ServiceClass,
)
from semantix_passbudget.domain.horizon import (
    conflict_components,
    evaluate_objective,
    select_queue_aware_nonoverlap,
)
from semantix_passbudget.domain.ledger import run_ledger
from semantix_passbudget.domain.models import DISABLED_STORAGE, CapacityProfile, Payload
from semantix_passbudget.domain.scheduler import Candidate, tie_break_key
from semantix_passbudget.domain.time import TimeInterval, UtcInstant

WINDOW = TimeInterval(UtcInstant(0), UtcInstant(120_000_000))


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
        source_revision_id="PBT",
        rationale="Property-based synthetic capacity.",
    )


def _payload(
    key: str,
    size: int,
    sequence: int,
    deadline_s: int | None,
    *,
    service_class: ServiceClass = ServiceClass.MANDATORY,
    ready_s: int = 0,
) -> Payload:
    return Payload(
        stable_key=key,
        logical_size_bytes=size,
        storage_size_bytes=size,
        ready_at=UtcInstant(ready_s * 1_000_000),
        service_class=service_class,
        deadline_at=None if deadline_s is None else UtcInstant(deadline_s * 1_000_000),
        deadline_severity=0,
        mission_priority=100 - sequence,
        queue_sequence=sequence,
        segmentation=SegmentationKind.ATOMIC_OBJECT,
        chunk_size_bytes=None,
        resume_supported=False,
    )


def _brute_force(
    candidates: tuple[Candidate, ...],
    profiles: dict[str, CapacityProfile],
    payloads: tuple[Payload, ...],
) -> tuple[str, ...]:
    """Search every pairwise non-overlapping subset, largest objective first."""
    best_key: tuple[object, ...] | None = None
    best: tuple[str, ...] = ()
    for size in range(len(candidates) + 1):
        for subset in combinations(candidates, size):
            if any(
                left.interval.overlaps(right.interval)
                for index, left in enumerate(subset)
                for right in subset[index + 1 :]
            ):
                continue
            ledger = run_ledger(subset, profiles, payloads, (), DISABLED_STORAGE, WINDOW)
            values = evaluate_objective(ledger, payloads, subset, WINDOW)
            tie = tuple(sorted(tie_break_key(item) for item in subset))
            key = (values.as_key(), tie)
            if (
                best_key is None
                or key[0] > best_key[0]
                or (key[0] == best_key[0] and key[1] < best_key[1])
            ):
                best_key = key
                best = tuple(sorted(item.stable_key for item in subset))
    return best


#: Two blocks far enough apart that no candidate in one can overlap a candidate in the other,
#: so every generated instance has at least two conflict components.
_BLOCK_A = (0, 20)
_BLOCK_B = (60, 80)


@given(
    starts_a=st.lists(
        st.integers(min_value=_BLOCK_A[0], max_value=_BLOCK_A[1]),
        min_size=2,
        max_size=3,
        unique=True,
    ),
    starts_b=st.lists(
        st.integers(min_value=_BLOCK_B[0], max_value=_BLOCK_B[1]),
        min_size=2,
        max_size=3,
        unique=True,
    ),
    lengths=st.lists(st.integers(min_value=3, max_value=14), min_size=6, max_size=6),
    capacities=st.lists(st.integers(min_value=1, max_value=9), min_size=6, max_size=6),
    sizes=st.lists(st.integers(min_value=2, max_value=11), min_size=3, max_size=3),
    ready=st.lists(st.integers(min_value=0, max_value=70), min_size=3, max_size=3),
    deadlines=st.lists(
        st.one_of(st.none(), st.integers(min_value=10, max_value=100)), min_size=3, max_size=3
    ),
    priority_mask=st.lists(st.booleans(), min_size=3, max_size=3),
)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_global_search_matches_exhaustive_subset_search(
    starts_a: list[int],
    starts_b: list[int],
    lengths: list[int],
    capacities: list[int],
    sizes: list[int],
    ready: list[int],
    deadlines: list[int | None],
    priority_mask: list[bool],
) -> None:
    starts = [*starts_a, *starts_b]
    candidates = tuple(
        Candidate(
            f"S{index}",
            f"GS-{index}",
            TimeInterval(
                UtcInstant(start * 1_000_000),
                UtcInstant((start + lengths[index]) * 1_000_000),
            ),
            capacities[index] * 1_000_000,
            0,
        )
        for index, start in enumerate(starts)
    )
    assert len(conflict_components(candidates)) >= 2, "the instance must span two components"
    profiles = {item.station_key: _profile(item.capacity_bytes) for item in candidates}
    payloads = tuple(
        _payload(
            f"P{index}",
            sizes[index] * 1_000_000,
            index + 1,
            deadlines[index],
            service_class=ServiceClass.PRIORITY if priority_mask[index] else ServiceClass.MANDATORY,
            ready_s=ready[index],
        )
        for index in range(3)
    )
    selected = select_queue_aware_nonoverlap(
        candidates, profiles, payloads, (), DISABLED_STORAGE, WINDOW
    ).sessions
    produced = tuple(sorted(item.stable_key for item in selected))
    expected = _brute_force(candidates, profiles, payloads)
    expected_sessions = tuple(item for item in candidates if item.stable_key in expected)
    ledger_produced = run_ledger(selected, profiles, payloads, (), DISABLED_STORAGE, WINDOW)
    ledger_expected = run_ledger(
        expected_sessions, profiles, payloads, (), DISABLED_STORAGE, WINDOW
    )
    # The objective value must match exactly; a different but equally optimal set is acceptable
    # only when the deterministic tie-break also matches, which `produced == expected` asserts.
    assert (
        evaluate_objective(ledger_produced, payloads, selected, WINDOW).as_key()
        == evaluate_objective(ledger_expected, payloads, expected_sessions, WINDOW).as_key()
    )
    assert produced == expected


@given(
    order=st.permutations(range(5)),
)
@settings(max_examples=20, deadline=None)
def test_candidate_input_order_never_changes_the_selection(order: list[int]) -> None:
    base = tuple(
        Candidate(
            f"S{index}",
            f"GS-{index}",
            TimeInterval(
                UtcInstant(index * 7_000_000),
                UtcInstant(index * 7_000_000 + 9_000_000),
            ),
            (index + 1) * 1_000_000,
            0,
        )
        for index in range(5)
    )
    profiles = {item.station_key: _profile(item.capacity_bytes) for item in base}
    payloads = (_payload("M1", 3_000_000, 1, 30),)
    reference = select_queue_aware_nonoverlap(
        base, profiles, payloads, (), DISABLED_STORAGE, WINDOW
    ).sessions
    permuted = select_queue_aware_nonoverlap(
        tuple(base[index] for index in order), profiles, payloads, (), DISABLED_STORAGE, WINDOW
    ).sessions
    assert [item.stable_key for item in reference] == [item.stable_key for item in permuted]


@given(
    starts_a=st.lists(
        st.integers(min_value=_BLOCK_A[0], max_value=_BLOCK_A[1]),
        min_size=2,
        max_size=3,
        unique=True,
    ),
    starts_b=st.lists(
        st.integers(min_value=_BLOCK_B[0], max_value=_BLOCK_B[1]),
        min_size=2,
        max_size=3,
        unique=True,
    ),
    lengths=st.lists(st.integers(min_value=3, max_value=14), min_size=6, max_size=6),
    capacities=st.lists(st.integers(min_value=1, max_value=9), min_size=6, max_size=6),
    order=st.permutations(range(6)),
)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_the_bounded_approximation_is_feasible_deterministic_and_never_better_than_optimal(
    starts_a: list[int],
    starts_b: list[int],
    lengths: list[int],
    capacities: list[int],
    order: list[int],
) -> None:
    starts = [*starts_a, *starts_b]
    candidates = tuple(
        Candidate(
            f"S{index}",
            f"GS-{index}",
            TimeInterval(
                UtcInstant(start * 1_000_000),
                UtcInstant((start + lengths[index]) * 1_000_000),
            ),
            capacities[index] * 1_000_000,
            0,
        )
        for index, start in enumerate(starts)
    )
    profiles = {item.station_key: _profile(item.capacity_bytes) for item in candidates}
    payloads = (
        _payload("M1", 4_000_000, 1, 40),
        _payload("P1", 9_000_000, 2, None, service_class=ServiceClass.PRIORITY, ready_s=5),
    )

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
    approximate = outcome.sessions

    # Feasible: a subset of the candidates, and schedulable on one transmitter.
    assert {item.stable_key for item in approximate} <= {item.stable_key for item in candidates}
    for left, right in combinations(approximate, 2):
        assert not left.interval.overlaps(right.interval)

    # Deterministic: the input order is not part of the answer. The strategy permutes six
    # positions but the instance may hold four, so the surplus positions are dropped.
    shuffled = [index for index in order if index < len(candidates)]
    permuted = select_queue_aware_nonoverlap(
        tuple(candidates[index] for index in shuffled),
        profiles,
        payloads,
        (),
        DISABLED_STORAGE,
        WINDOW,
        (),
        ExecutionStrategy.BOUNDED_APPROXIMATE,
    ).sessions
    assert [item.stable_key for item in permuted] == [item.stable_key for item in approximate]

    # Never better than the optimum, and honest about not being it.
    assert outcome.status.value == "APPROXIMATE"
    assert outcome.globally_optimal is False
    optimum = _brute_force(candidates, profiles, payloads)
    optimum_sessions = tuple(item for item in candidates if item.stable_key in optimum)
    approximate_key = evaluate_objective(
        run_ledger(approximate, profiles, payloads, (), DISABLED_STORAGE, WINDOW),
        payloads,
        approximate,
        WINDOW,
    ).as_key()
    optimum_key = evaluate_objective(
        run_ledger(optimum_sessions, profiles, payloads, (), DISABLED_STORAGE, WINDOW),
        payloads,
        optimum_sessions,
        WINDOW,
    ).as_key()
    assert approximate_key <= optimum_key
