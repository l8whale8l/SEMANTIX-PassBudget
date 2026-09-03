"""Metamorphic properties of the horizon-aware selection.

These are *not* an independent oracle for the objective's value. They check the two structural
claims the implementation makes on top of the objective, using an independently written
brute-force search over every pairwise non-overlapping subset:

* `SESSION_ADDITION_MONOTONICITY_V1` — restricting the search to maximal non-overlapping sets
  never loses the best selection;
* conflict-component decomposition — deciding components in time order reaches the same selection
  as searching all subsets at once, on instances small enough to enumerate.

The brute-force search here enumerates subsets itself and shares only the objective evaluation, so
a bug in component decomposition, maximality pruning or tie-breaking is visible.
"""

from __future__ import annotations

from itertools import combinations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from semantix_passbudget.domain.enums import (
    CapacityProvider,
    EvidenceState,
    SegmentationKind,
    ServiceClass,
)
from semantix_passbudget.domain.horizon import (
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


def _payload(key: str, size: int, sequence: int, deadline_s: int | None) -> Payload:
    return Payload(
        stable_key=key,
        logical_size_bytes=size,
        storage_size_bytes=size,
        ready_at=UtcInstant(0),
        service_class=ServiceClass.MANDATORY,
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


@given(
    starts=st.lists(st.integers(min_value=0, max_value=40), min_size=3, max_size=5, unique=True),
    lengths=st.lists(st.integers(min_value=3, max_value=14), min_size=5, max_size=5),
    capacities=st.lists(st.integers(min_value=1, max_value=9), min_size=5, max_size=5),
    deadline=st.integers(min_value=1, max_value=60),
)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_component_search_matches_exhaustive_subset_search(
    starts: list[int], lengths: list[int], capacities: list[int], deadline: int
) -> None:
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
        _payload("M1", 4_000_000, 1, deadline),
        _payload("M2", 9_000_000, 2, None),
    )
    selected, _ = select_queue_aware_nonoverlap(
        candidates, profiles, payloads, (), DISABLED_STORAGE, WINDOW
    )
    produced = tuple(sorted(item.stable_key for item in selected))
    expected = _brute_force(candidates, profiles, payloads)
    ledger_produced = run_ledger(selected, profiles, payloads, (), DISABLED_STORAGE, WINDOW)
    ledger_expected = run_ledger(
        tuple(item for item in candidates if item.stable_key in expected),
        profiles,
        payloads,
        (),
        DISABLED_STORAGE,
        WINDOW,
    )
    # The objective value must match exactly; a different but equally optimal set is acceptable
    # only when the deterministic tie-break also matches, which `produced == expected` asserts.
    assert (
        evaluate_objective(ledger_produced, payloads, selected, WINDOW).as_key()
        == evaluate_objective(
            ledger_expected,
            payloads,
            tuple(item for item in candidates if item.stable_key in expected),
            WINDOW,
        ).as_key()
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
    reference, _ = select_queue_aware_nonoverlap(
        base, profiles, payloads, (), DISABLED_STORAGE, WINDOW
    )
    permuted, _ = select_queue_aware_nonoverlap(
        tuple(base[index] for index in order), profiles, payloads, (), DISABLED_STORAGE, WINDOW
    )
    assert [item.stable_key for item in reference] == [item.stable_key for item in permuted]
