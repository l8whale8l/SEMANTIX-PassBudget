from __future__ import annotations

import pytest

from semantix_passbudget.domain.enums import (
    CapacityProvider,
    EvidenceState,
    SegmentationKind,
    ServiceClass,
)
from semantix_passbudget.domain.errors import DomainValidationError
from semantix_passbudget.domain.horizon import (
    conflict_components,
    maximal_nonoverlapping_sets,
    select_queue_aware_nonoverlap,
)
from semantix_passbudget.domain.models import DISABLED_STORAGE, CapacityProfile, Payload
from semantix_passbudget.domain.scheduler import Candidate
from semantix_passbudget.domain.time import TimeInterval, UtcInstant

WINDOW = TimeInterval(UtcInstant(0), UtcInstant(60_000_000))
MB = 1_000_000


def _candidate(key: str, start_s: int, end_s: int, capacity: int, rank: int = 0) -> Candidate:
    return Candidate(
        key,
        key,
        TimeInterval(UtcInstant(start_s * 1_000_000), UtcInstant(end_s * 1_000_000)),
        capacity,
        rank,
    )


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
        source_revision_id="AC-32",
        rationale="Synthetic horizon objective regression.",
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
        deadline_at=UtcInstant(deadline_s * 1_000_000) if deadline_s else None,
        deadline_severity=0,
        mission_priority=100 - sequence,
        queue_sequence=sequence,
        segmentation=SegmentationKind.ATOMIC_OBJECT,
        chunk_size_bytes=None,
        resume_supported=False,
    )


def _select(
    candidates: tuple[Candidate, ...],
    profiles: dict[str, CapacityProfile],
    payloads: tuple[Payload, ...],
) -> list[str]:
    outcome = select_queue_aware_nonoverlap(
        candidates, profiles, payloads, (), DISABLED_STORAGE, WINDOW
    )
    return [item.stable_key for item in outcome.sessions]


def test_mandatory_horizon_feasibility_precedes_capacity() -> None:
    x = _candidate("X", 0, 10, 10_000_000)
    y = _candidate("Y", 0, 4, 6_000_000)
    z = _candidate("Z", 20, 30, 10_000_000)
    assert _select(
        (x, y, z),
        {"X": _profile(10_000_000), "Y": _profile(6_000_000), "Z": _profile(10_000_000)},
        (_payload("M1", 6_000_000, 1, 5), _payload("M2", 10_000_000, 2, None)),
    ) == ["Y", "Z"]


def test_selection_reason_names_the_objective_step_that_decided_it() -> None:
    x = _candidate("X", 0, 10, 10_000_000)
    y = _candidate("Y", 0, 4, 6_000_000)
    z = _candidate("Z", 20, 30, 10_000_000)
    reasons = select_queue_aware_nonoverlap(
        (x, y, z),
        {"X": _profile(10_000_000), "Y": _profile(6_000_000), "Z": _profile(10_000_000)},
        (_payload("M1", 6_000_000, 1, 5), _payload("M2", 10_000_000, 2, None)),
        (),
        DISABLED_STORAGE,
        WINDOW,
    ).reasons
    assert reasons["Y"].value == "SESSION_SELECTED_MANDATORY_FEASIBILITY"


def test_non_conflicting_sessions_need_no_search() -> None:
    """A component with a single maximal set is committed without any rollout."""
    candidates = tuple(_candidate(f"S{i:02d}", i * 10, i * 10 + 5, 1_000) for i in range(40))
    profiles = {item.station_key: _profile(1_000) for item in candidates}
    assert _select(candidates, profiles, ()) == [item.stable_key for item in candidates]
    assert all(len(component) == 1 for component in conflict_components(candidates))


def test_maximal_sets_exclude_dominated_subsets() -> None:
    a = _candidate("A", 0, 5, 10)
    bridge = _candidate("B", 4, 11, 10)
    c = _candidate("C", 10, 15, 10)
    sets = {
        tuple(sorted(item.stable_key for item in alternative))
        for alternative in maximal_nonoverlapping_sets((a, bridge, c))
    }
    assert sets == {("A", "C"), ("B",)}


def test_dense_overlap_component_is_blocked_instead_of_approximating() -> None:
    # Twenty overlapping blocks of two interchangeable opportunities each produce far more
    # maximal non-overlapping sets than the enumeration budget, so the search reports an explicit
    # blocker instead of falling back to a byte-only heuristic.
    candidates = tuple(
        _candidate(f"S{index:02d}{side}", index * 11, index * 11 + 12, 1_000)
        for index in range(20)
        for side in ("A", "B")
    )
    profiles = {item.station_key: _profile(1_000) for item in candidates}
    with pytest.raises(DomainValidationError) as caught:
        _select(candidates, profiles, (_payload("M1", 1_000, 1, 5),))
    assert caught.value.detail.code == "QUEUE_HORIZON_SEARCH_BUDGET_EXCEEDED"


#: The two-component counterexample.
#:
#: A/B are one conflict component and C/D another, so no choice inside a single component can
#: reach the best answer. Committing component by component with a byte-maximising estimate of
#: the future picks B+C; the whole-horizon optimum is A+D. See
#: `test_cross_component_alternatives_are_evaluated_against_the_whole_horizon`.
_CROSS_COMPONENT_CANDIDATES = (
    _candidate("A", 0, 6, 11 * MB),
    _candidate("B", 5, 8, 5 * MB),
    _candidate("C", 10, 20, 10 * MB),
    _candidate("D", 10, 12, 5 * MB),
)
_CROSS_COMPONENT_PROFILES = {
    item.station_key: _profile(item.capacity_bytes) for item in _CROSS_COMPONENT_CANDIDATES
}
_CROSS_COMPONENT_PAYLOADS = (
    _payload("M", 5 * MB, 1, 15, service_class=ServiceClass.MANDATORY, ready_s=5),
    _payload("P", 11 * MB, 2, None, service_class=ServiceClass.PRIORITY, ready_s=0),
)


def test_cross_component_alternatives_are_evaluated_against_the_whole_horizon() -> None:
    """Regression: the objective is global, so component-local commitment is not enough.

    Both A+D and B+C keep the single MANDATORY payload on time, so the first two objective
    terms tie and the decision falls to policy utility. P is an 11 MB atomic object: it fits
    A exactly and fits nothing else, so choosing B in the first component destroys 11 MB of
    utility that no later component can recover. A+D also carries more scheduled bytes
    (16 MB against 15 MB), so it wins twice over and the answer is not a tie.
    """
    assert [
        tuple(item.stable_key for item in component)
        for component in conflict_components(_CROSS_COMPONENT_CANDIDATES)
    ] == [("A", "B"), ("D", "C")], "the counterexample needs exactly two conflict components"
    outcome = select_queue_aware_nonoverlap(
        _CROSS_COMPONENT_CANDIDATES,
        _CROSS_COMPONENT_PROFILES,
        _CROSS_COMPONENT_PAYLOADS,
        (),
        DISABLED_STORAGE,
        WINDOW,
    )
    selected, reasons = outcome.sessions, outcome.reasons
    assert [item.stable_key for item in selected] == ["A", "D"]
    assert outcome.status.value == "EXACT"
    assert outcome.globally_optimal is True
    # The reason names the step this component actually won on, not the step that separated the
    # two globally best combinations: both A and D beat their rivals on policy utility.
    assert reasons["A"].value == "SESSION_SELECTED_POLICY_UTILITY"
    assert reasons["D"].value == "SESSION_SELECTED_POLICY_UTILITY"


def test_cross_component_selection_is_independent_of_input_order() -> None:
    order = (3, 1, 0, 2)
    permuted = tuple(_CROSS_COMPONENT_CANDIDATES[index] for index in order)
    assert _select(permuted, _CROSS_COMPONENT_PROFILES, _CROSS_COMPONENT_PAYLOADS) == ["A", "D"]


def test_full_tie_resolves_by_lexical_station_id() -> None:
    x = _candidate("GS-X", 0, 10, 5_000)
    y = _candidate("GS-Y", 0, 10, 5_000)
    profiles = {"GS-X": _profile(5_000), "GS-Y": _profile(5_000)}
    payloads = (_payload("M1", 5_000, 1, None),)
    assert _select((x, y), profiles, payloads) == ["GS-X"]
    assert _select((y, x), profiles, payloads) == ["GS-X"]
