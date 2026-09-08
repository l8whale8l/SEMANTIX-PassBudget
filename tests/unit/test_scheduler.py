from semantix_passbudget.domain.scheduler import Candidate, select_maximum_nonoverlap
from semantix_passbudget.domain.time import TimeInterval, UtcInstant


def _candidate(key: str, start: int, end: int, capacity: int) -> Candidate:
    return Candidate(
        stable_key=key,
        station_key=key,
        interval=TimeInterval(UtcInstant(start), UtcInstant(end)),
        capacity_bytes=capacity,
        station_preference_rank=0,
    )


def test_endpoint_touch_is_not_conflict_and_tangent_is_invalid() -> None:
    left = _candidate("A", 0, 10, 10)
    right = _candidate("B", 10, 20, 10)
    assert not left.interval.overlaps(right.interval)
    assert {item.stable_key for item in select_maximum_nonoverlap((right, left))} == {"A", "B"}


def test_maximum_weight_pairwise_nonoverlap_not_one_per_component() -> None:
    left = _candidate("A", 0, 5, 6)
    bridge = _candidate("B", 4, 11, 10)
    right = _candidate("C", 10, 15, 6)
    selected = select_maximum_nonoverlap((bridge, right, left))
    assert [item.stable_key for item in selected] == ["A", "C"]
