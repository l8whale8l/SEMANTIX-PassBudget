from dataclasses import replace

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from semantix_passbudget.domain.capacity import calculate_contact_capacity
from semantix_passbudget.domain.models import ExactRate, RateSegment


@given(split_us=st.integers(min_value=1, max_value=479_999_999))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_equal_rate_segment_split_merge_invariance(golden_snapshot: object, split_us: int) -> None:
    snapshot = golden_snapshot
    station = snapshot.stations[0]
    constant = ExactRate(1_000_003, 7)
    merged = replace(
        station.capacity,
        rate_segments=(RateSegment(0, 0, 480_000_000, constant),),
    )
    split = replace(
        station.capacity,
        rate_segments=(
            RateSegment(0, 0, split_us, constant),
            RateSegment(1, split_us, 480_000_000, constant),
        ),
    )
    contact = snapshot.contacts[0]
    left = calculate_contact_capacity(contact, merged, snapshot.analysis_window)
    right = calculate_contact_capacity(contact, split, snapshot.analysis_window)
    assert left.capacity_bytes == right.capacity_bytes
