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

The scenario declares which of two strategies resolves that objective, and the two do not share
a candidate generator. The choice is made in `select_queue_aware_nonoverlap` before any candidate
generation runs, so neither mode can inherit the other's limits.

`EXACT_GLOBAL` (`overlap_objective_revision = QUEUE_AWARE_LEXICOGRAPHIC_HORIZON_V3`) establishes
the global optimum:

* Candidates are partitioned into interval-overlap conflict components. Sessions in different
  components never contend for the single TX resource, but they do contend for the **payload
  queue**, so the choices are not independent and are not decided independently.
* Inside a component every **maximal** set of pairwise non-overlapping sessions is enumerated.
  Non-maximal sets are skipped under the stated invariant `SESSION_ADDITION_MONOTONICITY_V1`:
  adding a session that conflicts with nothing already chosen only adds capacity at times that
  were previously idle, and therefore cannot lower any term of the objective.
  `tests/property/test_horizon_properties.py` checks this against a brute-force lexicographic
  oracle on randomised small instances.
* A component that offers exactly one maximal set contributes it unconditionally and costs no
  rollout. Only components that offer a genuine alternative branch.
* Every combination of the branching components' alternatives is scored with **one deterministic
  rollout over the whole analysis window**, and the lexicographic objective is compared on the
  complete selection. V2 instead committed component by component against a maximum-byte estimate
  of the future, which loses whenever an early component's choice destroys utility that no later
  component can recover; `tests/unit/test_horizon.py` carries the two-component counterexample
  that V2 got wrong.
* Three budgets bound it, and none of them degrades to a byte-only or greedy answer.
  `MAXIMAL_SET_BUDGET` bounds one component's maximal-set recursion
  (`QUEUE_HORIZON_SEARCH_BUDGET_EXCEEDED`); `GLOBAL_COMBINATION_BUDGET` bounds the product of the
  branching components' alternative counts (`QUEUE_HORIZON_GLOBAL_SEARCH_BUDGET_EXCEEDED`);
  `EXACT_WORK_BUDGET` bounds that product multiplied by the instance size, because one
  combination is one whole-horizon rollout and a combination count inside its budget can still
  miss the performance target (`QUEUE_HORIZON_EXACT_WORK_BUDGET_EXCEEDED`). A jointly optimal
  selection is NP-hard in general, so an instance dense enough in genuine conflicts is refused
  rather than approximated, and the caller is told which budget it exceeded.

The single-combination case costs no rollout at all, so a 20-station, 7-day analysis whose passes
rarely overlap is dominated by one ledger pass rather than by the search.

`BOUNDED_APPROXIMATE` (`approximate_objective_revision =
QUEUE_AWARE_BOUNDED_POLICY_FAMILY_V2`) answers the instances exact refuses:

* It never partitions into conflict components and never enumerates maximal sets. Each of the
  three fixed policies in `APPROXIMATE_POLICIES` reads the whole candidate set and returns one
  complete feasible selection by polynomial interval scheduling.
* Cost is three schedules plus at most three rollouts, whatever the overlap density. **None of
  the three exact budgets applies, and none of their errors can come out of this path** -- a
  single densely connected component can hold more maximal sets than `MAXIMAL_SET_BUDGET` allows
  while being perfectly ordinary to schedule greedily, and V1 of this family refused exactly
  those instances because it partitioned before it read the strategy.
* It guarantees feasibility and determinism, and nothing else. No selection outside the family
  is examined, so optimality is never established even where the answer happens to be optimal;
  the result says so in `optimization_status`, `globally_optimal` and a `NOT_GLOBALLY_OPTIMAL`
  warning.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from itertools import chain, product
from typing import Any

from .enums import ExecutionStrategy, OptimizationStatus, ReasonCode, ServiceClass
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
from .scheduler import (
    Candidate,
    TieBreakKey,
    select_maximum_nonoverlap,
    tie_break_key,
)
from .time import TimeInterval, UtcInstant

OVERLAP_OBJECTIVE_REVISION = "QUEUE_AWARE_LEXICOGRAPHIC_HORIZON_V3"
TIE_BREAK_PROFILE_REVISION = "STATION_RANK_COMPLETION_START_LEXICAL_V1"
MANDATORY_TARDINESS_REVISION = "MANDATORY_TARDINESS_V1"

#: Maximum maximal-independent-set enumeration nodes per conflict component.
MAXIMAL_SET_BUDGET = 4096

#: Maximum whole-horizon rollouts the exact search may evaluate.
#:
#: The product of the branching components' alternative counts, not a node count. Twelve two-way
#: conflicts fit; a thirteenth is refused rather than approximated.
GLOBAL_COMBINATION_BUDGET = 4096

#: Maximum estimated exact-search work, in rollout-scale units.
#:
#: The combination count alone says nothing about cost, because one combination is one full
#: `run_ledger` pass and that pass scales with the instance. Work is therefore estimated as
#: `combinations x (candidates + payloads + dependencies)` before any rollout runs.
#:
#: Calibration: the specification's reference analysis (700 contacts, 10,000 payloads, no
#: dependencies) is 10,700 units per rollout and takes about 1.4 s on an ordinary developer
#: machine. 250,000 units is therefore roughly 23 rollouts, about 33 s there -- deliberately
#: inside the 60 s target of `P0_FUNCTIONAL_SPEC.md` §15.2 with room for slower hardware, so a
#: budget-passing exact run does not quietly blow the performance target instead.
EXACT_WORK_BUDGET = 250_000

#: The bounded approximation. Named so a result can say which algorithm produced it.
APPROXIMATE_OBJECTIVE_REVISION = "QUEUE_AWARE_BOUNDED_POLICY_FAMILY_V2"


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


def _global_budget_exceeded(branching_components: int) -> DomainValidationError:
    return DomainValidationError(
        ErrorDetail(
            code="QUEUE_HORIZON_GLOBAL_SEARCH_BUDGET_EXCEEDED",
            message=(
                "Exact whole-horizon queue-aware selection exceeded the global enumeration budget "
                f"of {GLOBAL_COMBINATION_BUDGET} combinations across {branching_components} "
                "conflict components that offer a genuine alternative. The objective is global, "
                "so the alternatives cannot be decided component by component, and a jointly "
                "optimal selection is NP-hard. The result is refused rather than approximated by "
                "a byte-only or greedy rule; reduce the overlap density or raise the budget "
                "deliberately."
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


def _selection_order(item: Candidate) -> tuple[UtcInstant, str]:
    return (item.interval.start, item.stable_key)


@dataclass(frozen=True, slots=True)
class SelectionOutcome:
    """The selection and, just as importantly, what the run established about it."""

    sessions: tuple[Candidate, ...]
    reasons: dict[str, ReasonCode]
    status: OptimizationStatus
    globally_optimal: bool
    algorithm_revision: str
    #: Always `None` today, and deliberately so.
    #:
    #: A bound on the *scheduled byte* term alone is cheap and exact -- it is the `NETWORK_ONLY`
    #: maximum. But that is the fifth term of a lexicographic objective, and a gap on one term is
    #: not a gap on the objective: a selection can be byte-optimal and still miss a MANDATORY
    #: deadline the optimum meets. Publishing it under the name `optimality_gap` would claim
    #: something the number does not support, so the field stays null until a bound on the whole
    #: objective exists.
    optimality_gap: int | None = None


def _work_budget_exceeded(combinations: int, scale: int) -> DomainValidationError:
    return DomainValidationError(
        ErrorDetail(
            code="QUEUE_HORIZON_EXACT_WORK_BUDGET_EXCEEDED",
            message=(
                f"Exact queue-aware selection would cost about {combinations * scale} work units "
                f"({combinations} whole-horizon rollouts over an instance of scale {scale}) "
                f"against a budget of {EXACT_WORK_BUDGET}. The combination count is inside its "
                "own budget, but running it would miss the performance target rather than "
                "produce an answer. Reduce the instance or the overlap density, or choose "
                "execution_strategy=BOUNDED_APPROXIMATE deliberately -- nothing switches modes "
                "on your behalf."
            ),
            scope="schedule",
            field_paths=("contacts", "payloads"),
            affected_branches=("schedule", "queue"),
        )
    )


def _partition(
    candidates: tuple[Candidate, ...],
) -> tuple[tuple[Candidate, ...], tuple[tuple[tuple[Candidate, ...], ...], ...]]:
    """Split components into the forced ones and the ones that offer a genuine alternative.

    Exact only. This enumerates maximal sets, which is exponential in one component's overlap
    density and is what `MAXIMAL_SET_BUDGET` bounds. The bounded approximation must never reach
    it -- an approximation that inherits the exact search's combinatorics has no reason to exist.
    """
    fixed: list[Candidate] = []
    branching: list[tuple[tuple[Candidate, ...], ...]] = []
    for component in conflict_components(candidates):
        alternatives = maximal_nonoverlapping_sets(component)
        if len(alternatives) == 1:
            # Nothing competes with this component's sessions, so no rollout can change them.
            fixed.extend(alternatives[0])
        else:
            branching.append(alternatives)
    return tuple(fixed), tuple(branching)


def _forced(fixed: tuple[Candidate, ...]) -> tuple[tuple[Candidate, ...], dict[str, ReasonCode]]:
    selected = tuple(sorted(fixed, key=_selection_order))
    return selected, {
        item.stable_key: ReasonCode.SESSION_SELECTED_MAX_LOGICAL_BYTES for item in selected
    }


def _greedy_schedule(
    candidates: tuple[Candidate, ...],
    order: Callable[[Candidate], tuple[Any, ...]],
) -> tuple[Candidate, ...]:
    """Take candidates in a total order, keeping each one that still fits.

    Classic interval scheduling: the result is pairwise non-overlapping by construction and the
    order is total, so the answer does not depend on how the candidates arrived. Quadratic in the
    worst case and linear in practice -- either way polynomial, which is the whole point.
    """
    chosen: list[Candidate] = []
    for item in sorted(candidates, key=order):
        if all(not item.interval.overlaps(taken.interval) for taken in chosen):
            chosen.append(item)
    return tuple(sorted(chosen, key=_selection_order))


def _max_capacity_schedule(candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    """The exact maximum-capacity selection: the `NETWORK_ONLY` weighted-interval program."""
    return select_maximum_nonoverlap(candidates)


def _earliest_finish_schedule(candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    """Earliest finishing time first, which maximises how many opportunities are used."""
    return _greedy_schedule(
        candidates,
        lambda item: (
            item.interval.end.microseconds,
            item.interval.start.microseconds,
            tie_break_key(item),
        ),
    )


def _densest_first_schedule(candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    """Most bytes per unit of occupied time first: short, high-capacity passes before long ones.

    The density is an exact `Fraction`, never a binary float: this is an ordering over
    authoritative capacity values and two candidates must compare the same way on every machine.
    """
    return _greedy_schedule(
        candidates,
        lambda item: (
            -Fraction(
                item.capacity_bytes,
                max(
                    1,
                    item.interval.end.microseconds - item.interval.start.microseconds,
                ),
            ),
            tie_break_key(item),
        ),
    )


#: The deterministic polynomial schedules the bounded approximation chooses between.
#:
#: Each takes the whole candidate set and returns one complete feasible selection, so the family
#: never enumerates maximal sets and never meets the exact search's combinatorics. They are
#: chosen to disagree in the ways that matter: total capacity is what the byte term wants, an
#: early finish is what a deadline wants, and density is what a queue arriving over time wants.
#: The family being fixed and small is what makes the mode affordable and reproducible, and
#: equally what makes it an approximation rather than a search.
APPROXIMATE_POLICIES: tuple[Callable[[tuple[Candidate, ...]], tuple[Candidate, ...]], ...] = (
    _max_capacity_schedule,
    _earliest_finish_schedule,
    _densest_first_schedule,
)


def _score(
    selection: tuple[Candidate, ...],
    profiles_by_station: dict[str, CapacityProfile],
    payloads: tuple[Payload, ...],
    dependencies: tuple[PayloadDependency, ...],
    storage: StorageConfig,
    analysis_window: TimeInterval,
    delivery_events: tuple[SyntheticDeliveryEvent, ...],
) -> ObjectiveKey:
    ledger = run_ledger(
        selection,
        profiles_by_station,
        payloads,
        dependencies,
        storage,
        analysis_window,
        delivery_events,
    )
    return evaluate_objective(ledger, payloads, selection, analysis_window).as_key()


def select_queue_aware_nonoverlap(
    candidates: tuple[Candidate, ...],
    profiles_by_station: dict[str, CapacityProfile],
    payloads: tuple[Payload, ...],
    dependencies: tuple[PayloadDependency, ...],
    storage: StorageConfig,
    analysis_window: TimeInterval,
    delivery_events: tuple[SyntheticDeliveryEvent, ...] = (),
    strategy: ExecutionStrategy = ExecutionStrategy.EXACT_GLOBAL,
) -> SelectionOutcome:
    """Select sessions under the declared strategy, and report what that strategy established.

    The strategy is decided here, before any candidate generation, because the two modes do not
    share one. Exact enumerates maximal sets and is bounded by three budgets; the approximation
    builds its candidate selections by polynomial interval scheduling and is bounded by nothing,
    because there is nothing about it to bound.
    """
    if strategy is ExecutionStrategy.BOUNDED_APPROXIMATE:
        return _select_bounded_approximate(
            candidates,
            profiles_by_station,
            payloads,
            dependencies,
            storage,
            analysis_window,
            delivery_events,
        )
    return _select_exact_global(
        candidates,
        profiles_by_station,
        payloads,
        dependencies,
        storage,
        analysis_window,
        delivery_events,
    )


def _select_exact_global(
    candidates: tuple[Candidate, ...],
    profiles_by_station: dict[str, CapacityProfile],
    payloads: tuple[Payload, ...],
    dependencies: tuple[PayloadDependency, ...],
    storage: StorageConfig,
    analysis_window: TimeInterval,
    delivery_events: tuple[SyntheticDeliveryEvent, ...],
) -> SelectionOutcome:
    fixed, branching = _partition(candidates)
    if not branching:
        selected, reasons = _forced(fixed)
        return SelectionOutcome(
            sessions=selected,
            reasons=reasons,
            status=OptimizationStatus.EXACT,
            globally_optimal=True,
            algorithm_revision=OVERLAP_OBJECTIVE_REVISION,
        )

    combinations = 1
    for alternatives in branching:
        combinations *= len(alternatives)
        if combinations > GLOBAL_COMBINATION_BUDGET:
            raise _global_budget_exceeded(len(branching))
    # The largest selection any combination can produce: an honest upper bound on the number of
    # sessions one rollout walks.
    sessions_in_play = len(fixed) + sum(
        max(len(alternative) for alternative in alternatives) for alternatives in branching
    )
    scale = sessions_in_play + len(payloads) + len(dependencies)
    if combinations * scale > EXACT_WORK_BUDGET:
        raise _work_budget_exceeded(combinations, scale)

    scored: list[
        tuple[
            ObjectiveKey,
            tuple[TieBreakKey, ...],
            tuple[tuple[Candidate, ...], ...],
            tuple[Candidate, ...],
        ]
    ] = []
    for choice in product(*branching):
        selection = tuple(sorted((*fixed, *chain.from_iterable(choice)), key=_selection_order))
        key = _score(
            selection,
            profiles_by_station,
            payloads,
            dependencies,
            storage,
            analysis_window,
            delivery_events,
        )
        scored.append((key, _selection_tie_break(selection), choice, selection))
    # Descending on the lexicographic objective, ascending on the tie-break: a total order.
    scored.sort(key=lambda item: (_negated(item[0]), item[1]))
    best_key, _, best_choice, best_selection = scored[0]

    reasons = {item.stable_key: ReasonCode.SESSION_SELECTED_MAX_LOGICAL_BYTES for item in fixed}
    for position in range(len(branching)):
        # The best combination that decided this component differently: comparing against it
        # names the objective step this component's sessions actually won on, rather than the
        # step that separated the two globally best combinations.
        rival = next(
            (key for key, _, choice, _ in scored if choice[position] != best_choice[position]),
            None,
        )
        for item in best_choice[position]:
            reasons[item.stable_key] = _decisive_reason(best_key, rival)
    return SelectionOutcome(
        sessions=best_selection,
        reasons=reasons,
        status=OptimizationStatus.EXACT,
        globally_optimal=True,
        algorithm_revision=OVERLAP_OBJECTIVE_REVISION,
    )


def _select_bounded_approximate(
    candidates: tuple[Candidate, ...],
    profiles_by_station: dict[str, CapacityProfile],
    payloads: tuple[Payload, ...],
    dependencies: tuple[PayloadDependency, ...],
    storage: StorageConfig,
    analysis_window: TimeInterval,
    delivery_events: tuple[SyntheticDeliveryEvent, ...],
) -> SelectionOutcome:
    """Best of a fixed, small family of deterministic polynomial schedules.

    Each policy reads the whole candidate set and returns one complete feasible selection, so the
    cost is `len(APPROXIMATE_POLICIES)` schedules plus at most that many rollouts -- whatever the
    overlap density, and with no conflict-component decomposition and no maximal-set enumeration
    anywhere on this path. That separation is the point: a single densely connected component can
    hold more maximal sets than the exact budget allows, and an approximation that inherited that
    limit would refuse exactly the instances it exists to answer.

    It is an approximation and says so: no selection outside the family is ever examined, so
    nothing here establishes optimality even on an instance where the answer happens to be
    optimal. The result is always feasible -- interval scheduling never returns two overlapping
    sessions -- and always the same for the same input, because every ordering here is total.
    """
    by_key: dict[tuple[str, ...], tuple[Candidate, ...]] = {}
    for policy in APPROXIMATE_POLICIES:
        selection = policy(candidates)
        by_key[tuple(item.stable_key for item in selection)] = selection
    ordered = [by_key[key] for key in sorted(by_key)]

    if len(ordered) == 1:
        # The family agreed, so there is nothing to score and no rollout to spend. The grade
        # still reports the mode rather than the instance: a caller who asked for the bounded
        # family gets a result this mode cannot prove optimal in general, and under-claiming is
        # the safe direction for a field named `globally_optimal`.
        selection = ordered[0]
        return SelectionOutcome(
            sessions=selection,
            reasons={
                item.stable_key: ReasonCode.SESSION_SELECTED_MAX_LOGICAL_BYTES for item in selection
            },
            status=OptimizationStatus.APPROXIMATE,
            globally_optimal=False,
            algorithm_revision=APPROXIMATE_OBJECTIVE_REVISION,
        )

    scored = [
        (
            _score(
                selection,
                profiles_by_station,
                payloads,
                dependencies,
                storage,
                analysis_window,
                delivery_events,
            ),
            _selection_tie_break(selection),
            selection,
        )
        for selection in ordered
    ]
    scored.sort(key=lambda item: (_negated(item[0]), item[1]))
    best_key, _, best_selection = scored[0]
    reason = _decisive_reason(best_key, scored[1][0])
    return SelectionOutcome(
        sessions=best_selection,
        reasons={item.stable_key: reason for item in best_selection},
        status=OptimizationStatus.APPROXIMATE,
        globally_optimal=False,
        algorithm_revision=APPROXIMATE_OBJECTIVE_REVISION,
    )
