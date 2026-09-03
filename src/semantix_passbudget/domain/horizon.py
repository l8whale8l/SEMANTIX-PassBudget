"""Horizon-aware `QUEUE_AWARE` session selection.

`NETWORK_ONLY` maximises logical bytes over pairwise non-overlapping whole opportunities and is
solved exactly by the dynamic program in `scheduler.py`. `QUEUE_AWARE` instead applies the
lexicographic objective of the accepted v1.2 baseline:

    1. physical, temporal and dependency feasibility
    2. maximise the MANDATORY on-time vector
    3. minimise MANDATORY tardiness
    4. maximise policy utility
    5. maximise scheduled logical bytes
    6. deterministic tie-break

Scope of the exactness claim (`overlap_objective_revision =
QUEUE_AWARE_LEXICOGRAPHIC_HORIZON_V2`):

* Candidates are partitioned into interval-overlap conflict components. Sessions in different
  components never contend for the single TX resource.
* Inside a component every **maximal** set of pairwise non-overlapping sessions is enumerated and
  scored with a full deterministic rollout, so the component's own choice is exhaustive rather
  than greedy. Non-maximal sets are skipped under the stated invariant
  `SESSION_ADDITION_MONOTONICITY_V1`: adding a session that conflicts with nothing already chosen
  only adds capacity at times that were previously idle, and therefore cannot lower any term of
  the objective. `tests/property/test_horizon_properties.py` checks this against a brute-force
  lexicographic oracle on randomised small instances.
* Components are decided in time order, each scored against a rollout that already contains the
  committed prefix and a maximum-byte estimate of every later component. A jointly optimal choice
  across all components is NP-hard; it is not claimed here and the revision name records that.
* Enumeration is bounded by `MAXIMAL_SET_BUDGET`. Exceeding it raises
  `QUEUE_HORIZON_SEARCH_BUDGET_EXCEEDED`. The search never degrades silently to a byte-only
  heuristic.

The single-alternative case costs no rollout at all, so a 20-station, 7-day analysis whose passes
rarely overlap is dominated by one ledger pass rather than by the search.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import ReasonCode, ServiceClass
from .errors import DomainValidationError, ErrorDetail
from .ledger import LedgerResult, run_ledger
from .models import (
    CapacityProfile,
    Payload,
    PayloadDependency,
    StorageConfig,
    SyntheticDeliveryEvent,
)
from .queue import queue_order_key
from .scheduler import Candidate, TieBreakKey, select_maximum_nonoverlap, tie_break_key
from .time import TimeInterval, UtcInstant

OVERLAP_OBJECTIVE_REVISION = "QUEUE_AWARE_LEXICOGRAPHIC_HORIZON_V2"
TIE_BREAK_PROFILE_REVISION = "STATION_RANK_COMPLETION_START_LEXICAL_V1"
MANDATORY_TARDINESS_REVISION = "MANDATORY_TARDINESS_V1"

#: Maximum maximal-independent-set enumeration nodes per conflict component.
MAXIMAL_SET_BUDGET = 4096


ObjectiveKey = tuple[tuple[int, ...], int, tuple[int, ...], int]


@dataclass(frozen=True, slots=True)
class ObjectiveValues:
    """Lexicographic objective. Every field is maximised; tardiness is stored negated."""

    mandatory_on_time: tuple[int, ...]
    negated_mandatory_tardiness_us: int
    policy_utility: tuple[int, ...]
    scheduled_logical_bytes: int

    def as_key(self) -> ObjectiveKey:
        return (
            self.mandatory_on_time,
            self.negated_mandatory_tardiness_us,
            self.policy_utility,
            self.scheduled_logical_bytes,
        )


def _budget_exceeded(component_size: int) -> DomainValidationError:
    return DomainValidationError(
        ErrorDetail(
            code="QUEUE_HORIZON_SEARCH_BUDGET_EXCEEDED",
            message=(
                "Exact queue-aware conflict evaluation exceeded the enumeration budget of "
                f"{MAXIMAL_SET_BUDGET} maximal non-overlapping sets in one overlap component of "
                f"{component_size} candidates. The objective is not approximated; reduce the "
                "overlap density or raise the budget deliberately."
            ),
            scope="schedule",
            field_paths=("contacts",),
            affected_branches=("schedule", "queue"),
        )
    )


def conflict_components(candidates: tuple[Candidate, ...]) -> tuple[tuple[Candidate, ...], ...]:
    ordered = sorted(
        candidates, key=lambda item: (item.interval.start, item.interval.end, item.stable_key)
    )
    if not ordered:
        return ()
    components: list[list[Candidate]] = []
    current = [ordered[0]]
    frontier_end = ordered[0].interval.end
    for candidate in ordered[1:]:
        if candidate.interval.start < frontier_end:
            current.append(candidate)
            frontier_end = max(frontier_end, candidate.interval.end)
        else:
            components.append(current)
            current = [candidate]
            frontier_end = candidate.interval.end
    components.append(current)
    return tuple(tuple(component) for component in components)


def maximal_nonoverlapping_sets(
    component: tuple[Candidate, ...],
) -> tuple[tuple[Candidate, ...], ...]:
    """Every maximal pairwise non-overlapping subset of one conflict component.

    A set is maximal when no further candidate fits into any remaining gap. At each step only the
    candidates that start before the earliest available end are viable next choices: any other
    choice would leave room to insert that earliest-ending candidate, so the result would not be
    maximal. This enumerates each maximal set exactly once.
    """
    ordered = tuple(
        sorted(
            component,
            key=lambda item: (item.interval.start, item.interval.end, item.stable_key),
        )
    )
    results: list[tuple[Candidate, ...]] = []
    visited = 0

    def recurse(last_end: UtcInstant | None, chosen: tuple[Candidate, ...]) -> None:
        nonlocal visited
        visited += 1
        if visited > MAXIMAL_SET_BUDGET:
            raise _budget_exceeded(len(component))
        available = [
            item for item in ordered if last_end is None or item.interval.start >= last_end
        ]
        if not available:
            results.append(chosen)
            return
        earliest_end = min(item.interval.end for item in available)
        for item in available:
            if item.interval.start < earliest_end:
                recurse(item.interval.end, (*chosen, item))

    recurse(None, ())
    return tuple(results)


def evaluate_objective(
    ledger: LedgerResult,
    payloads: tuple[Payload, ...],
    sessions: tuple[Candidate, ...],
    analysis_window: TimeInterval,
) -> ObjectiveValues:
    progress = {item.payload_key: item for item in ledger.progress}
    ordered = tuple(sorted(payloads, key=queue_order_key))
    mandatory = tuple(
        payload for payload in ordered if payload.service_class is ServiceClass.MANDATORY
    )
    on_time: list[int] = []
    tardiness = 0
    for payload in mandatory:
        item = progress.get(payload.stable_key)
        completion = item.modeled_tx_complete_at if item else None
        if completion is None:
            on_time.append(0)
            if payload.deadline_at is not None:
                tardiness += max(
                    0, analysis_window.end.microseconds - payload.deadline_at.microseconds
                )
            continue
        if payload.deadline_at is None or completion <= payload.deadline_at:
            on_time.append(1)
        else:
            on_time.append(0)
            tardiness += completion.microseconds - payload.deadline_at.microseconds
    utility = tuple(
        progress[payload.stable_key].allocated_bytes if payload.stable_key in progress else 0
        for payload in ordered
    )
    return ObjectiveValues(
        mandatory_on_time=tuple(on_time),
        negated_mandatory_tardiness_us=-tardiness,
        policy_utility=utility,
        scheduled_logical_bytes=sum(item.capacity_bytes for item in sessions),
    )


def _selection_tie_break(items: tuple[Candidate, ...]) -> tuple[TieBreakKey, ...]:
    return tuple(sorted(tie_break_key(item) for item in items))


def _negated(key: ObjectiveKey) -> tuple[tuple[int, ...], int, tuple[int, ...], int]:
    """Invert the objective so ascending sort order means "best first"."""
    return (
        tuple(-item for item in key[0]),
        -key[1],
        tuple(-item for item in key[2]),
        -key[3],
    )


def _decisive_reason(best: ObjectiveKey, runner_up: ObjectiveKey | None) -> ReasonCode:
    """Name the objective step that separated the winner from the next-best alternative."""
    if runner_up is None:
        return ReasonCode.SESSION_SELECTED_MAX_LOGICAL_BYTES
    if best[0] != runner_up[0] or best[1] != runner_up[1]:
        return ReasonCode.SESSION_SELECTED_MANDATORY_FEASIBILITY
    if best[2] != runner_up[2]:
        return ReasonCode.SESSION_SELECTED_POLICY_UTILITY
    if best[3] != runner_up[3]:
        return ReasonCode.SESSION_SELECTED_MAX_LOGICAL_BYTES
    return ReasonCode.SESSION_SELECTED_TIE_BREAK


def select_queue_aware_nonoverlap(
    candidates: tuple[Candidate, ...],
    profiles_by_station: dict[str, CapacityProfile],
    payloads: tuple[Payload, ...],
    dependencies: tuple[PayloadDependency, ...],
    storage: StorageConfig,
    analysis_window: TimeInterval,
    delivery_events: tuple[SyntheticDeliveryEvent, ...] = (),
) -> tuple[tuple[Candidate, ...], dict[str, ReasonCode]]:
    """Return the selected sessions and the reason code that justified each selection."""
    components = conflict_components(candidates)
    chosen: list[Candidate] = []
    reasons: dict[str, ReasonCode] = {}
    for index, component in enumerate(components):
        alternatives = maximal_nonoverlapping_sets(component)
        if len(alternatives) == 1:
            # No competing maximal set exists: the component contributes every session it has.
            for item in alternatives[0]:
                reasons[item.stable_key] = ReasonCode.SESSION_SELECTED_MAX_LOGICAL_BYTES
            chosen.extend(alternatives[0])
            continue
        future = tuple(
            candidate
            for later in components[index + 1 :]
            for candidate in select_maximum_nonoverlap(later)
        )
        scored: list[tuple[ObjectiveKey, tuple[TieBreakKey, ...], tuple[Candidate, ...]]] = []
        for alternative in alternatives:
            trial = tuple(chosen) + alternative + future
            ledger = run_ledger(
                trial,
                profiles_by_station,
                payloads,
                dependencies,
                storage,
                analysis_window,
                delivery_events,
            )
            values = evaluate_objective(ledger, payloads, trial, analysis_window)
            scored.append((values.as_key(), _selection_tie_break(alternative), alternative))
        # Descending on the lexicographic objective, ascending on the tie-break: a total order.
        scored.sort(key=lambda item: (_negated(item[0]), item[1]))
        best_key, _, best_alternative = scored[0]
        best_reason = _decisive_reason(best_key, scored[1][0] if len(scored) > 1 else None)
        for item in best_alternative:
            reasons[item.stable_key] = best_reason
        chosen.extend(best_alternative)
    selected = tuple(sorted(chosen, key=lambda item: (item.interval.start, item.stable_key)))
    return selected, reasons
