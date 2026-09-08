from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.domain.enums import (
    AdmissionPolicy,
    DeliveryAssumption,
    DependencyKind,
    ReclaimGranularity,
    ReleaseTrigger,
    ReserveEnforcement,
    StorageMode,
)
from semantix_passbudget.domain.errors import DomainValidationError
from semantix_passbudget.domain.models import PayloadDependency, ScenarioSnapshot, StorageConfig
from semantix_passbudget.interfaces.dto import load_fixture

FIXTURES = Path(__file__).resolve().parents[2] / "src" / "semantix_passbudget" / "fixtures"


def _snapshot(name: str) -> ScenarioSnapshot:
    return load_fixture(FIXTURES / name).to_domain()


def _run(name: str) -> dict[str, Any]:
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    return service.run(_snapshot(name)).result


def _storage(
    enforcement: ReserveEnforcement,
    *,
    release: ReleaseTrigger = ReleaseTrigger.NEVER,
    assumption: DeliveryAssumption = DeliveryAssumption.NONE,
) -> StorageConfig:
    return StorageConfig(
        mode=StorageMode.ENABLED,
        physical_capacity_bytes=200_000_000,
        reserve_bytes=20_000_000,
        initial_occupancy_bytes=50_000_000,
        reserve_enforcement=enforcement,
        admission_policy=AdmissionPolicy.REJECT_NEW,
        release_trigger=release,
        delivery_assumption=assumption,
        reclaim_granularity=ReclaimGranularity.OBJECT,
    )


def test_overlap_oracle_selects_a2_and_suppresses_d() -> None:
    result = _run("PB-GOLDEN-OVERLAP-01.json")
    metrics = result["metrics"]
    assert metrics["candidate_capacity_sum_bytes"] == 440_000_000
    assert metrics["scheduled_unique_capacity_bytes"] == 400_000_000
    assert metrics["suppressed_capacity_bytes"] == 40_000_000
    assert result["suppressed_candidates"] == [
        {
            "candidate_stable_key": "candidate/D1",
            "capacity_bytes": 40_000_000,
            "reason_codes": [{"code": "SESSION_SUPPRESSED_TX_RESOURCE_CONFLICT"}],
        }
    ]


def test_queue_first_session_and_completion_oracles() -> None:
    result = _run("PB-GOLDEN-QUEUE-01.json")
    first = [row for row in result["payload_allocations"] if row["session_key"] == "candidate/A1"]
    assert [(row["payload_key"], row["allocated_bytes"]) for row in first] == [
        ("P-ALERT", 50_000),
        ("P-THUMB", 950_000),
        ("P-MASK", 4_000_000),
        ("P-ORIGINAL", 55_000_000),
    ]
    assert [row["end"] for row in first] == [
        "2027-01-01T00:11:00.800000Z",
        "2027-01-01T00:11:16.000000Z",
        "2027-01-01T00:12:20.000000Z",
        "2027-01-01T00:19:00.000000Z",
    ]
    original = next(row for row in result["payload_progress"] if row["payload_key"] == "P-ORIGINAL")
    assert original["remaining_bytes"] == 0
    assert original["modeled_tx_complete_at"] == "2027-01-01T06:12:20.000000Z"
    assert first[-1]["remaining_bytes_after"] == 85_000_000


def test_bundle_actionable_without_delivery_assumption_is_not_observed() -> None:
    """AC-26A1: required members complete at 00:11:16; nothing claims ground actionability."""
    result = _run("PB-GOLDEN-QUEUE-01.json")
    bundle = result["bundles"][0]
    assert bundle["modeled_required_members_tx_complete_at"] == "2027-01-01T00:11:16.000000Z"
    assert bundle["assumed_actionable_at"] is None
    assert bundle["delivery_confirmation_state"] == "NOT_OBSERVED"
    assert bundle["actionable_status"] == "ACHIEVED"


def test_queue_input_permutation_preserves_semantic_results() -> None:
    snapshot = _snapshot("PB-GOLDEN-QUEUE-01.json")
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    baseline = service.run(snapshot)
    permuted = service.run(
        replace(
            snapshot,
            stations=tuple(reversed(snapshot.stations)),
            contacts=tuple(reversed(snapshot.contacts)),
            payloads=tuple(reversed(snapshot.payloads)),
        )
    )
    assert baseline.input_snapshot_hash == permuted.input_snapshot_hash
    assert baseline.result_content_hash == permuted.result_content_hash


def test_storage_soft_and_hard_reserve_oracles() -> None:
    snapshot = _snapshot("PB-GOLDEN-QUEUE-01.json")
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    soft_result = service.run(replace(snapshot, storage=_storage(ReserveEnforcement.SOFT))).result[
        "storage"
    ]
    assert soft_result["final_occupancy_bytes"] == 195_000_000
    assert soft_result["hard_overflow_bytes"] == 0
    assert soft_result["reserve_breach_bytes"] == 15_000_000
    assert soft_result["admissions"][-1]["reason_codes"] == [{"code": "RESERVE_BREACH_SOFT"}]

    hard_run = service.run(replace(snapshot, storage=_storage(ReserveEnforcement.HARD)))
    hard_result = hard_run.result["storage"]
    assert hard_result["final_occupancy_bytes"] == 55_000_000
    assert hard_result["reserve_breach_bytes"] == 0
    assert hard_result["rejected_object_count"] == 1
    assert hard_result["rejected_bytes"] == 140_000_000
    assert hard_result["admissions"][-1] == {
        "payload_key": "P-ORIGINAL",
        "admitted": False,
        "occupancy_after_bytes": 55_000_000,
        "reason_codes": [{"code": "ADMISSION_REJECTED_HARD_RESERVE"}],
    }
    assert hard_run.result["metrics"]["payload_allocated_bytes"] == 5_000_000


def test_release_never_holds_every_object() -> None:
    """AC-25A: transferring bytes never reclaims storage when release_trigger is NEVER."""
    snapshot = _snapshot("PB-GOLDEN-QUEUE-01.json")
    storage = replace(_storage(ReserveEnforcement.SOFT), initial_occupancy_bytes=0, reserve_bytes=0)
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    result = service.run(replace(snapshot, storage=storage)).result["storage"]
    assert result["final_occupancy_bytes"] == 145_000_000
    assert result["released_bytes"] == 0


def test_tx_end_proxy_releases_only_complete_objects() -> None:
    """AC-25C: with the TX_END proxy the small objects release; an incomplete one holds."""
    snapshot = _snapshot("PB-GOLDEN-QUEUE-01.json")
    truncated = replace(
        snapshot,
        analysis_window=replace(
            snapshot.analysis_window, end=snapshot.contacts[0].true_interval.end
        ),
        contacts=snapshot.contacts[:1],
        storage=replace(
            _storage(
                ReserveEnforcement.SOFT,
                release=ReleaseTrigger.TX_END,
                assumption=DeliveryAssumption.TX_END_EQUALS_DELIVERED,
            ),
            initial_occupancy_bytes=0,
            reserve_bytes=0,
        ),
    )
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    run = service.run(truncated)
    storage = run.result["storage"]
    assert storage["released_bytes"] == 5_000_000
    assert storage["final_occupancy_bytes"] == 140_000_000
    original = next(
        row for row in run.result["payload_progress"] if row["payload_key"] == "P-ORIGINAL"
    )
    assert {code["code"] for code in original["reason_codes"]} >= {"RELEASE_HELD_INCOMPLETE_OBJECT"}
    assert {warning["code"] for warning in run.result["warnings"]} >= {
        "ASSUMED_DELIVERY_PROXY_RESULT"
    }


def test_synthetic_acknowledgement_ledger_matches_oracle() -> None:
    """AC-25B: occupancy after each TEST_SYNTHETIC acknowledgement."""
    result = _run("PB-GOLDEN-ACK-01.json")
    occupancy = [
        (event["payload_key"], event["occupancy_bytes"])
        for event in result["run_events"]
        if event["event_kind"] == "OBJECT_RELEASED"
    ]
    assert occupancy == [
        ("P-ALERT", 144_950_000),
        ("P-THUMB", 144_000_000),
        ("P-MASK", 140_000_000),
    ]
    assert result["storage"]["final_occupancy_bytes"] == 140_000_000
    assert "SYNTHETIC_TEST_DELIVERY_EVENTS_ONLY" in {
        warning["code"] for warning in result["warnings"]
    }


def test_same_timestamp_release_precedes_admission() -> None:
    """AC-40: at one instant the release and reclaim commit before the new admission."""
    result = _run("PB-GOLDEN-ACK-01.json")
    generation = [
        event
        for event in result["run_events"]
        if event["event_at"] == "2027-01-01T00:05:00.000000Z"
    ]
    assert [event["event_kind"] for event in generation[:2]] == [
        "OBJECT_GENERATED",
        "OBJECT_ADMITTED",
    ]
    assert [event["event_order"] for event in generation] == list(range(len(generation)))


def test_dependency_cycle_is_rejected_before_allocations() -> None:
    snapshot = _snapshot("PB-GOLDEN-QUEUE-01.json")
    cyclic = replace(
        snapshot,
        dependencies=(
            PayloadDependency("P-ALERT", "P-THUMB", DependencyKind.SEND_AFTER),
            PayloadDependency("P-THUMB", "P-ALERT", DependencyKind.SEND_AFTER),
        ),
    )
    with pytest.raises(DomainValidationError) as caught:
        cyclic.validate()
    assert caught.value.detail.code == "DEPENDENCY_CYCLE"


def test_send_after_dependency_defers_until_predecessor_completion() -> None:
    snapshot = _snapshot("PB-GOLDEN-QUEUE-01.json")
    ordered = replace(
        snapshot,
        dependencies=(PayloadDependency("P-MASK", "P-ALERT", DependencyKind.SEND_AFTER),),
    )
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    result = service.run(ordered).result
    first = [row for row in result["payload_allocations"] if row["session_key"] == "candidate/A1"]
    order = [row["payload_key"] for row in first]
    assert order.index("P-MASK") < order.index("P-ALERT")


def test_queue_aware_with_storage_disabled_reports_not_applicable() -> None:
    """AC-P0-15 / AC-48: allocation and backlog are computed; storage is N/A, not zero."""
    result = _run("PB-GOLDEN-QUEUE-01.json")
    assert result["metrics"]["payload_allocated_bytes"] == 145_000_000
    assert result["metrics"]["payload_remaining_bytes"] == 0
    storage = result["storage"]
    assert storage["calculation_status"] == "NOT_APPLICABLE"
    assert storage["physical_capacity_bytes"] is None
    assert storage["final_occupancy_bytes"] is None
    assert storage["admissions"] == []
    rows = {row["metric_code"]: row for row in result["run_metrics"]}
    assert rows["STORAGE_FINAL_OCCUPANCY_BYTES"]["calculation_status"] == "NOT_APPLICABLE"
    assert rows["STORAGE_FINAL_OCCUPANCY_BYTES"]["value_integer"] is None
