from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.orbit.provider import OrbitContactProvider
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.comparison import compare_results
from semantix_passbudget.application.composition import (
    build_run_repository,
    describe_persistence,
)
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.domain.enums import (
    AdmissionPolicy,
    DeliveryAssumption,
    ReclaimGranularity,
    ReleaseTrigger,
    ReserveEnforcement,
    StorageMode,
)
from semantix_passbudget.domain.errors import DomainValidationError
from semantix_passbudget.domain.models import StorageConfig
from semantix_passbudget.domain.time import UtcInstant
from semantix_passbudget.interfaces.dto import load_fixture_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="passbudget",
        description=(
            "Deterministic mission data-budget calculator. Every command runs without a database "
            "unless --persist is given."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a fixture and print its input hash")
    validate.add_argument("fixture")
    run = commands.add_parser("run", help="run a fixture and write the typed result")
    run.add_argument("fixture")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument(
        "--persist",
        action="store_true",
        help="also store the run in the configured local database (SQLite by default)",
    )
    commands.add_parser("verify-golden", help="check every golden fixture against its oracle")
    compare = commands.add_parser("compare", help="compare two result files")
    compare.add_argument("baseline_result", type=Path)
    compare.add_argument("candidate_result", type=Path)
    show = commands.add_parser("show", help="read a stored run back from the local database")
    show.add_argument("run_id")
    commands.add_parser("where", help="print the resolved persistence tier and database location")
    return parser


def _service() -> RunScenarioService:
    """Pure-calculation service. No database, no file, no server."""
    return RunScenarioService(
        SyntheticContactProvider(),
        InMemoryRunRepository(),
        orbit_provider=OrbitContactProvider(),
    )


def _persistent_service() -> tuple[RunScenarioService, str]:
    """Service backed by the configured local store. SQLite unless told otherwise."""
    repository, tier = build_run_repository(default="sqlite")
    service = RunScenarioService(
        SyntheticContactProvider(), repository, orbit_provider=OrbitContactProvider()
    )
    return service, tier


def _storage(enforcement: ReserveEnforcement) -> StorageConfig:
    return StorageConfig(
        mode=StorageMode.ENABLED,
        physical_capacity_bytes=200_000_000,
        reserve_bytes=20_000_000,
        initial_occupancy_bytes=50_000_000,
        reserve_enforcement=enforcement,
        admission_policy=AdmissionPolicy.REJECT_NEW,
        release_trigger=ReleaseTrigger.NEVER,
        delivery_assumption=DeliveryAssumption.NONE,
        reclaim_granularity=ReclaimGranularity.OBJECT,
    )


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _verify_golden(service: RunScenarioService) -> dict[str, Any]:
    core = service.run(load_fixture_source("PB-GOLDEN-CORE-01").to_domain())
    overlap = service.run(load_fixture_source("PB-GOLDEN-OVERLAP-01").to_domain())
    horizon = service.run(load_fixture_source("PB-GOLDEN-HORIZON-01").to_domain())
    ack = service.run(load_fixture_source("PB-GOLDEN-ACK-01").to_domain())
    queue_snapshot = load_fixture_source("PB-GOLDEN-QUEUE-01").to_domain()
    queue = service.run(queue_snapshot)
    hard = service.run(replace(queue_snapshot, storage=_storage(ReserveEnforcement.HARD)))
    soft = service.run(replace(queue_snapshot, storage=_storage(ReserveEnforcement.SOFT)))
    orbit = service.run(load_fixture_source("PB-GOLDEN-ORB-01").to_domain())

    core_metrics = cast(dict[str, Any], core.result["metrics"])
    stations = {
        station["station_key"]: (
            station["geometric_contact_count"],
            station["candidate_capacity_sum_bytes"],
        )
        for station in cast(list[dict[str, Any]], core_metrics["stations"])
    }
    _expect(
        stations == {"GS-A": (4, 240_000_000), "GS-B": (4, 160_000_000), "GS-C": (8, 160_000_000)},
        "core golden station totals differ from the literal oracle",
    )
    _expect(
        core_metrics["scheduled_unique_capacity_bytes"] == 560_000_000,
        "core golden scheduled unique capacity differs from the literal oracle",
    )
    _expect(
        core.result["orbit_dependency"]["calculation_status"] == "NOT_APPLICABLE"
        and core.result["decision_grade"] == "CONCEPT_ONLY",
        "core golden orbit dependency or decision grade differs from the literal oracle",
    )
    overlap_metrics = cast(dict[str, Any], overlap.result["metrics"])
    _expect(
        overlap_metrics["candidate_capacity_sum_bytes"] == 440_000_000
        and overlap_metrics["scheduled_unique_capacity_bytes"] == 400_000_000,
        "overlap golden result differs from the literal oracle",
    )
    first_allocations = [
        item
        for item in cast(list[dict[str, Any]], queue.result["payload_allocations"])
        if item["session_key"] == "candidate/A1"
    ]
    _expect(
        [item["allocated_bytes"] for item in first_allocations]
        == [50_000, 950_000, 4_000_000, 55_000_000],
        "queue golden first-session allocation differs from the literal oracle",
    )
    _expect(
        [item["end"] for item in first_allocations]
        == [
            "2027-01-01T00:11:00.800000Z",
            "2027-01-01T00:11:16.000000Z",
            "2027-01-01T00:12:20.000000Z",
            "2027-01-01T00:19:00.000000Z",
        ],
        "queue golden modeled completion times differ from the literal oracle",
    )
    horizon_selected = [
        item["candidate_stable_key"]
        for item in cast(list[dict[str, Any]], horizon.result["scheduled_sessions"])
    ]
    _expect(
        horizon_selected == ["candidate/Y1", "candidate/Z1"],
        "horizon golden selection differs from the AC-32 oracle",
    )
    _expect(
        cast(dict[str, Any], hard.result["storage"])["final_occupancy_bytes"] == 55_000_000,
        "hard storage golden result differs from the literal oracle",
    )
    soft_storage = cast(dict[str, Any], soft.result["storage"])
    _expect(
        soft_storage["reserve_breach_bytes"] == 15_000_000
        and soft_storage["final_occupancy_bytes"] == 195_000_000
        and soft_storage["hard_overflow_bytes"] == 0,
        "soft storage golden result differs from the literal oracle",
    )
    ack_storage = cast(dict[str, Any], ack.result["storage"])
    _expect(
        ack_storage["final_occupancy_bytes"] == 140_000_000
        and ack_storage["released_bytes"] == 5_000_000,
        "synthetic-acknowledgement storage result differs from the AC-25B oracle",
    )
    orbit_summary = _verify_orbit_golden(orbit)
    return {
        "core": {
            "fixture_id": core.result["fixture_id"],
            "decision_grade": core.result["decision_grade"],
            "orbit_dependency": core.result["orbit_dependency"],
            "geometric_contact_count": core_metrics["geometric_contact_count"],
            "candidate_capacity_sum_bytes": core_metrics["candidate_capacity_sum_bytes"],
            "scheduled_unique_capacity_bytes": core_metrics["scheduled_unique_capacity_bytes"],
            "stations": core_metrics["stations"],
            "input_snapshot_hash": core.input_snapshot_hash,
            "result_content_hash": core.result_content_hash,
        },
        "overlap": {
            "candidate_capacity_sum_bytes": overlap_metrics["candidate_capacity_sum_bytes"],
            "scheduled_unique_capacity_bytes": overlap_metrics["scheduled_unique_capacity_bytes"],
            "suppressed": [
                item["candidate_stable_key"]
                for item in cast(list[dict[str, Any]], overlap.result["suppressed_candidates"])
            ],
            "result_content_hash": overlap.result_content_hash,
        },
        "queue": {
            "first_session_allocated_bytes": [
                item["allocated_bytes"] for item in first_allocations
            ],
            "first_session_completion": [item["end"] for item in first_allocations],
            "payload_allocated_bytes": cast(dict[str, Any], queue.result["metrics"])[
                "payload_allocated_bytes"
            ],
            "payload_remaining_bytes": cast(dict[str, Any], queue.result["metrics"])[
                "payload_remaining_bytes"
            ],
            "result_content_hash": queue.result_content_hash,
        },
        "horizon": {
            "selected": horizon_selected,
            "result_content_hash": horizon.result_content_hash,
        },
        "storage": {
            "hard_final_occupancy_bytes": cast(dict[str, Any], hard.result["storage"])[
                "final_occupancy_bytes"
            ],
            "soft_final_occupancy_bytes": soft_storage["final_occupancy_bytes"],
            "soft_reserve_breach_bytes": soft_storage["reserve_breach_bytes"],
            "ack_final_occupancy_bytes": ack_storage["final_occupancy_bytes"],
            "ack_released_bytes": ack_storage["released_bytes"],
            "result_content_hash": ack.result_content_hash,
        },
        "orbit": orbit_summary,
    }


#: Effective downlink used by PB-GOLDEN-ORB-01: 2 Mbit/s pre-loss * 1/2 efficiency = 125000 B/s.
_ORBIT_GOLDEN_EFFECTIVE_BYTES_PER_S = 125_000


def _verify_orbit_golden(orbit: Any) -> dict[str, Any]:
    """Check the full ORBIT_DERIVED flow end to end.

    The substantive anchors are not copied product numbers. The pass counts are the ones NASA GMAT
    produced for this synthetic orbit and these two stations in `EVD-ORB-02` window W1 (MIDLAT 4,
    EQUATOR 3), so they check the product engine against the independent oracle, not against itself.
    The capacity is checked by the arithmetic identity contact_time x effective_rate, and the
    selection outcome is checked by which model outputs were sent.
    """
    result = cast(dict[str, Any], orbit.result)
    metrics = cast(dict[str, Any], result["metrics"])
    _expect(
        result["contact_source"] == "ORBIT_DERIVED",
        "orbit golden must be an ORBIT_DERIVED run",
    )
    stations = {
        station["station_key"]: station["geometric_contact_count"]
        for station in cast(list[dict[str, Any]], metrics["stations"])
    }
    _expect(
        stations == {"SYN-GS-MIDLAT": 4, "SYN-GS-EQUATOR": 3},
        "orbit golden daily pass counts differ from the GMAT oracle (EVD-ORB-02 W1)",
    )
    _expect(
        metrics["geometric_contact_count"] == 7,
        "orbit golden must report seven daily passes",
    )
    # Arithmetic identity: every candidate session's capacity equals its modeled active seconds
    # times the effective byte rate, floored once. This is the hand-computable check the spec asks
    # for, applied to the engine-derived durations rather than to hard-coded numbers.
    for candidate in cast(list[dict[str, Any]], result["candidate_sessions"]):
        start, end = candidate["usable_start"], candidate["usable_end"]
        if start is None or end is None:
            continue
        active_us = UtcInstant.parse(end).microseconds - UtcInstant.parse(start).microseconds
        expected = active_us * _ORBIT_GOLDEN_EFFECTIVE_BYTES_PER_S // 1_000_000
        _expect(
            candidate["capacity_bytes"] == expected,
            "orbit golden capacity is not contact_time x effective_rate for a candidate session",
        )
    progress = {
        item["payload_key"]: item for item in cast(list[dict[str, Any]], result["payload_progress"])
    }
    _expect(
        progress["WILDFIRE-DETECT"]["state"] == "COMPLETED"
        and progress["FIGHTER-TRACK"]["state"] == "COMPLETED"
        and progress["SHIP-DETECT"]["state"] == "PARTIAL",
        "orbit golden selection differs: wildfire and fighter must complete and ship stay partial",
    )
    _expect(
        result["optimization"]["globally_optimal"] is True,
        "orbit golden must be globally optimal under EXACT_GLOBAL",
    )
    _expect(
        "가정 기반 추정값" in result["safety_notice"],
        "orbit golden must carry the assumption-based (not KMU performance) safety notice",
    )
    return {
        "fixture_id": result["fixture_id"],
        "contact_source": result["contact_source"],
        "daily_pass_count": metrics["geometric_contact_count"],
        "daily_contact_time_us": metrics["geometric_duration_us"],
        "stations": stations,
        "daily_capacity_bytes": metrics["candidate_capacity_sum_bytes"],
        "payload_allocated_bytes": metrics["payload_allocated_bytes"],
        "payload_remaining_bytes": metrics["payload_remaining_bytes"],
        "sent": {key: progress[key]["state"] for key in sorted(progress)},
        "input_snapshot_hash": orbit.input_snapshot_hash,
        "result_content_hash": orbit.result_content_hash,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "where":
            print(json.dumps(describe_persistence(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "show":
            service, tier = _persistent_service()
            stored = service.get(args.run_id)
            if stored is None:
                print(
                    json.dumps(
                        {
                            "error": {
                                "code": "RUN_NOT_FOUND",
                                "message": "No run with that identifier exists in the local store.",
                                "scope": "run",
                                "field_paths": ["run_id"],
                                "affected_branches": [],
                                "details": {"persistent_tier": tier},
                            }
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 2
            print(json.dumps(stored.metadata_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "compare":
            baseline = json.loads(args.baseline_result.read_text(encoding="utf-8"))
            candidate = json.loads(args.candidate_result.read_text(encoding="utf-8"))
            comparison = compare_results(baseline["result"], candidate["result"])
            print(json.dumps(comparison, ensure_ascii=False, indent=2))
            return 0
        if args.command == "verify-golden":
            print(json.dumps(_verify_golden(_service()), ensure_ascii=False, indent=2))
            return 0
        fixture = load_fixture_source(args.fixture)
        persist = getattr(args, "persist", False)
        service, tier = _persistent_service() if persist else (_service(), "memory")
        if args.command == "validate":
            input_hash = service.validate(fixture.to_domain())
            print(json.dumps({"valid": True, "input_snapshot_hash": input_hash}, indent=2))
            return 0
        run = service.run(fixture.to_domain())
        if args.command == "run":
            envelope = {**run.metadata_dict(), "result": run.result}
            args.output.write_text(
                json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps({**run.metadata_dict(), "persistent_tier": tier}, indent=2))
            return 0
        raise RuntimeError("unreachable CLI command")
    except DomainValidationError as exc:
        print(json.dumps({"error": exc.detail.as_dict()}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
