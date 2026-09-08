"""`NETWORK_ONLY` whole-opportunity selection.

Exact maximum-weight pairwise non-overlapping subset over the candidate intervals. A conflict
component is a calculation group, not a "choose exactly one" constraint: two candidates inside one
component that do not overlap each other may both be selected.
"""

from __future__ import annotations

from dataclasses import dataclass

from .time import TimeInterval

TIE_BREAK_PROFILE_REVISION = "STATION_RANK_COMPLETION_START_LEXICAL_V1"


@dataclass(frozen=True, slots=True)
class Candidate:
    stable_key: str
    station_key: str
    interval: TimeInterval
    capacity_bytes: int
    station_preference_rank: int


TieBreakKey = tuple[int, int, int, str, str]


def tie_break_key(item: Candidate) -> TieBreakKey:
    """`station_preference_rank ASC -> completion/session end ASC -> start ASC -> station lexical`.

    `NETWORK_ONLY` has no payload completion, so the session end is the completion surrogate that
    the accepted tie-break profile names. `stable_key` closes the final degenerate tie so the
    comparator is total.
    """
    return (
        item.station_preference_rank,
        item.interval.end.microseconds,
        item.interval.start.microseconds,
        item.station_key,
        item.stable_key,
    )


def _selection_key(items: tuple[Candidate, ...]) -> tuple[TieBreakKey, ...]:
    return tuple(sorted(tie_break_key(item) for item in items))


def _better(left: tuple[Candidate, ...], right: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    left_weight = sum(item.capacity_bytes for item in left)
    right_weight = sum(item.capacity_bytes for item in right)
    if left_weight != right_weight:
        return left if left_weight > right_weight else right
    return left if _selection_key(left) < _selection_key(right) else right


def select_maximum_nonoverlap(candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.interval.end.microseconds,
                item.interval.start.microseconds,
                item.station_preference_rank,
                item.station_key,
                item.stable_key,
            ),
        )
    )
    compatible: list[int] = []
    for index, item in enumerate(ordered):
        previous = -1
        for prior in range(index - 1, -1, -1):
            if ordered[prior].interval.end <= item.interval.start:
                previous = prior
                break
        compatible.append(previous)

    best: list[tuple[Candidate, ...]] = [()]
    for index, item in enumerate(ordered):
        include = best[compatible[index] + 1] + (item,)
        exclude = best[index]
        best.append(_better(include, exclude))
    return tuple(sorted(best[-1], key=lambda item: (item.interval.start, item.stable_key)))
