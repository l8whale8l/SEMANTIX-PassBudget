"""Per-UTC-date transfer budget read model.

The daily budget is a *re-aggregation* of an already-computed run result, not a new calculation.
These cases pin the aggregation contract with independent, hand-computed expected values —
midnight-crossing attribution, partial boundary days, multi-day spread, a no-contact day inside
the window, and the sum-preservation invariant — and then confirm the golden run and the HTTP
surface agree. The pure function is exercised with fabricated minimal results so each expectation
is derived by hand, not read back from the engine it is meant to check.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from semantix_passbudget.application.composition import build_application
from semantix_passbudget.application.daily_budget import AGGREGATION_BASIS, daily_budget
from semantix_passbudget.interfaces.api.app import app
from semantix_passbudget.interfaces.dto import load_public_fixture


def _scheduled(station: str, start: str, end: str, capacity: int) -> dict[str, Any]:
    return {
        "stable_key": f"scheduled/{station}/{start}",
        "station_key": station,
        "usable_start": start,
        "usable_end": end,
        "capacity_bytes": capacity,
    }


def _candidate(station: str, start: str, end: str, capacity: int) -> dict[str, Any]:
    return {
        "stable_key": f"candidate/{station}/{start}",
        "station_key": station,
        "usable_start": start,
        "usable_end": end,
        "capacity_bytes": capacity,
    }


def _access(station: str, aos: str) -> dict[str, Any]:
    return {"stable_key": f"geometric/{station}/{aos}", "station_key": station, "true_aos": aos}


def _result(
    scheduled: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    accesses: list[dict[str, Any]],
    scheduled_unique: int,
) -> dict[str, Any]:
    return {
        "calculation_status": "COMPUTED",
        "scheduled_sessions": scheduled,
        "candidate_sessions": candidates,
        "geometric_accesses": accesses,
        "metrics": {"scheduled_unique_capacity_bytes": scheduled_unique},
    }


def test_midnight_crossing_session_counts_wholly_on_its_start_day() -> None:
    # One session runs 23:30 on the 3rd to 00:30 on the 4th. The contract attributes it in full to
    # the UTC start day (the 3rd); the 4th sees no scheduled capacity from it.
    result = _result(
        scheduled=[
            _scheduled("GS-A", "2026-09-03T23:30:00.000000Z", "2026-09-04T00:30:00.000000Z", 1000)
        ],
        candidates=[
            _candidate("GS-A", "2026-09-03T23:30:00.000000Z", "2026-09-04T00:30:00.000000Z", 1000)
        ],
        accesses=[_access("GS-A", "2026-09-03T23:30:00.000000Z")],
        scheduled_unique=1000,
    )
    window = {"start": "2026-09-03T00:00:00.000000Z", "end": "2026-09-05T00:00:00.000000Z"}

    budget = daily_budget(result, window)
    by_date = {row["utc_date"]: row for row in budget["days"]}

    assert by_date["2026-09-03"]["scheduled_capacity_bytes"] == 1000
    assert by_date["2026-09-03"]["scheduled_session_count"] == 1
    assert by_date["2026-09-04"]["scheduled_capacity_bytes"] == 0
    assert by_date["2026-09-04"]["scheduled_session_count"] == 0
    assert budget["sum_preserved"] is True
    assert budget["aggregation_basis"] == AGGREGATION_BASIS


def test_partial_boundary_days_are_flagged_full_days_are_not() -> None:
    # Window opens mid-day on the 3rd and closes mid-day on the 5th → 3rd and 5th are partial,
    # the 4th is a full UTC day.
    window = {"start": "2026-09-03T06:00:00.000000Z", "end": "2026-09-05T18:00:00.000000Z"}
    result = _result([], [], [], 0)

    budget = daily_budget(result, window)
    partial = {row["utc_date"]: row["is_partial"] for row in budget["days"]}

    assert partial == {"2026-09-03": True, "2026-09-04": False, "2026-09-05": True}


def test_multi_day_spread_preserves_sum_and_separates_days() -> None:
    result = _result(
        scheduled=[
            _scheduled("GS-A", "2026-09-03T10:00:00.000000Z", "2026-09-03T10:10:00.000000Z", 300),
            _scheduled("GS-B", "2026-09-04T11:00:00.000000Z", "2026-09-04T11:10:00.000000Z", 700),
            _scheduled("GS-A", "2026-09-04T20:00:00.000000Z", "2026-09-04T20:10:00.000000Z", 500),
        ],
        candidates=[],
        accesses=[
            _access("GS-A", "2026-09-03T10:00:00.000000Z"),
            _access("GS-B", "2026-09-04T11:00:00.000000Z"),
            _access("GS-A", "2026-09-04T20:00:00.000000Z"),
        ],
        scheduled_unique=1500,
    )
    window = {"start": "2026-09-03T00:00:00.000000Z", "end": "2026-09-05T00:00:00.000000Z"}

    budget = daily_budget(result, window)
    by_date = {row["utc_date"]: row for row in budget["days"]}

    assert by_date["2026-09-03"]["scheduled_capacity_bytes"] == 300
    assert by_date["2026-09-04"]["scheduled_capacity_bytes"] == 1200  # 700 + 500
    assert by_date["2026-09-04"]["scheduled_session_count"] == 2
    assert budget["period_scheduled_capacity_from_days_bytes"] == 1500
    assert budget["sum_preserved"] is True


def test_no_contact_day_inside_window_is_known_zero_not_absent() -> None:
    # Contacts on the 3rd and the 5th; the 4th has none. Within the window the 4th must appear as an
    # explicit 0, distinguishable from a day outside the analysed period (which is simply absent).
    result = _result(
        scheduled=[
            _scheduled("GS-A", "2026-09-03T10:00:00.000000Z", "2026-09-03T10:10:00.000000Z", 400),
            _scheduled("GS-A", "2026-09-05T10:00:00.000000Z", "2026-09-05T10:10:00.000000Z", 600),
        ],
        candidates=[],
        accesses=[
            _access("GS-A", "2026-09-03T10:00:00.000000Z"),
            _access("GS-A", "2026-09-05T10:00:00.000000Z"),
        ],
        scheduled_unique=1000,
    )
    # Half-open window [3rd 00:00, 6th 00:00) covers the 3rd, 4th and 5th (the 6th is excluded).
    window = {"start": "2026-09-03T00:00:00.000000Z", "end": "2026-09-06T00:00:00.000000Z"}

    budget = daily_budget(result, window)
    dates = [row["utc_date"] for row in budget["days"]]
    by_date = {row["utc_date"]: row for row in budget["days"]}

    assert dates == ["2026-09-03", "2026-09-04", "2026-09-05"]
    assert by_date["2026-09-04"]["scheduled_capacity_bytes"] == 0
    assert by_date["2026-09-04"]["geometric_contact_count"] == 0
    assert "2026-09-06" not in by_date  # outside the half-open window: absent, not a zero row


def test_end_exactly_on_midnight_adds_no_trailing_empty_day() -> None:
    # A half-open window ending exactly at midnight of the 4th covers only the 3rd.
    window = {"start": "2026-09-03T00:00:00.000000Z", "end": "2026-09-04T00:00:00.000000Z"}
    budget = daily_budget(_result([], [], [], 0), window)
    assert [row["utc_date"] for row in budget["days"]] == ["2026-09-03"]


def test_without_window_falls_back_to_observed_span_without_partial_claims() -> None:
    result = _result(
        scheduled=[
            _scheduled("GS-A", "2026-09-03T10:00:00.000000Z", "2026-09-03T10:10:00.000000Z", 400)
        ],
        candidates=[],
        accesses=[_access("GS-A", "2026-09-03T10:00:00.000000Z")],
        scheduled_unique=400,
    )
    budget = daily_budget(result, None)

    assert budget["analysis_window"] is None
    assert [row["utc_date"] for row in budget["days"]] == ["2026-09-03"]
    assert budget["days"][0]["is_partial"] is False
    assert budget["sum_preserved"] is True


def test_golden_run_daily_budget_matches_contract_example() -> None:
    application = build_application(default_persistence="memory")
    stored = application.runs.run(load_public_fixture("PB-GOLDEN-ORB-01").to_domain())
    window = stored.input_snapshot_payload["analysis_window"]

    budget = daily_budget(stored.result, window)

    assert budget["period_scheduled_unique_capacity_bytes"] == 526555476
    assert budget["sum_preserved"] is True
    assert len(budget["days"]) == 1
    day = budget["days"][0]
    assert day["utc_date"] == "2026-09-03"
    assert day["is_partial"] is False
    assert day["geometric_contact_count"] == 7
    assert day["scheduled_session_count"] == 7
    assert day["scheduled_capacity_bytes"] == 526555476


def test_daily_budget_endpoint_returns_run_and_404_for_unknown() -> None:
    client = TestClient(app)
    created = client.post("/api/v1/runs", json={"fixture": "PB-GOLDEN-ORB-01"})
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    ok = client.get(f"/api/v1/runs/{run_id}/daily-budget")
    assert ok.status_code == 200
    body = ok.json()
    assert body["run_id"] == run_id
    assert body["aggregation_basis"] == AGGREGATION_BASIS
    assert body["sum_preserved"] is True
    assert body["days"][0]["utc_date"] == "2026-09-03"

    missing = client.get("/api/v1/runs/does-not-exist/daily-budget")
    assert missing.status_code == 404
