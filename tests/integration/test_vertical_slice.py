from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.domain.models import ScenarioSnapshot
from semantix_passbudget.interfaces.api.app import app
from semantix_passbudget.interfaces.cli.main import main


def _service() -> RunScenarioService:
    return RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())


def test_golden_counts_intervals_and_totals(golden_snapshot: ScenarioSnapshot) -> None:
    result = _service().run(golden_snapshot).result
    metrics = result["metrics"]
    assert metrics["geometric_contact_count"] == 16
    assert metrics["candidate_capacity_sum_bytes"] == 560_000_000
    assert metrics["scheduled_unique_capacity_bytes"] == 560_000_000
    assert metrics["suppressed_capacity_bytes"] == 0
    assert metrics["geometric_access_gap"] == {"scope": "INTERNAL", "max_us": 5_040_000_000}
    assert metrics["modeled_active_data_gap"] == {"scope": "INTERNAL", "max_us": 5_120_000_000}
    stations = {item["station_key"]: item for item in metrics["stations"]}
    assert (
        stations["GS-A"]["geometric_contact_count"],
        stations["GS-A"]["candidate_capacity_sum_bytes"],
    ) == (4, 240_000_000)
    assert (
        stations["GS-B"]["geometric_contact_count"],
        stations["GS-B"]["candidate_capacity_sum_bytes"],
    ) == (4, 160_000_000)
    assert (
        stations["GS-C"]["geometric_contact_count"],
        stations["GS-C"]["candidate_capacity_sum_bytes"],
    ) == (8, 160_000_000)
    first_a = next(
        item
        for item in result["modeled_contacts"]
        if item["geometric_stable_key"] == "geometric/A1"
    )
    assert (first_a["usable_start"], first_a["usable_end"]) == (
        "2027-01-01T00:11:00.000000Z",
        "2027-01-01T00:19:00.000000Z",
    )
    last_c = next(
        item for item in result["geometric_accesses"] if item["stable_key"] == "geometric/C8"
    )
    assert (last_c["true_aos"], last_c["true_los"]) == (
        "2027-01-01T22:40:00.000000Z",
        "2027-01-01T22:46:00.000000Z",
    )
    assert result["orbit_dependency"] == {"calculation_status": "NOT_APPLICABLE", "value": None}
    assert result["contact_source"] == "SYNTHETIC_INJECTED"
    assert result["decision_grade"] == "CONCEPT_ONLY"


def test_network_only_leaves_queue_and_storage_not_applicable(
    golden_snapshot: ScenarioSnapshot,
) -> None:
    """AC-38 / AC-P0-15: an absent optional branch is N/A, never zero and never infinite."""
    run = _service().run(golden_snapshot)
    assert run.result["payload_allocations"] == []
    assert run.result["metrics"]["payload_allocated_bytes"] is None
    assert run.result["storage"]["calculation_status"] == "NOT_APPLICABLE"
    assert run.result["storage"]["final_occupancy_bytes"] is None
    stages = {stage["stage_code"]: stage["status"] for stage in run.stages}
    assert stages["QUEUE"] == "NOT_APPLICABLE"
    assert stages["STORAGE"] == "NOT_APPLICABLE"


def test_permutation_preserves_semantic_hash(golden_snapshot: ScenarioSnapshot) -> None:
    service = _service()
    baseline = service.run(golden_snapshot)
    variant = service.run(
        replace(
            golden_snapshot,
            stations=tuple(reversed(golden_snapshot.stations)),
            contacts=tuple(reversed(golden_snapshot.contacts)),
        )
    )
    assert baseline.input_snapshot_hash == variant.input_snapshot_hash
    assert baseline.result_content_hash == variant.result_content_hash
    assert baseline.run_id != variant.run_id
    assert baseline.run_record_hash != variant.run_record_hash


def test_api_and_cli_use_same_result_hash(fixture_path: Path, tmp_path: Path) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/health").status_code == 200
    created = client.post("/api/v1/runs", json={"fixture": "PB-GOLDEN-CORE-01"})
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    fetched = client.get(f"/api/v1/runs/{run_id}")
    results = client.get(f"/api/v1/runs/{run_id}/results")
    assert fetched.status_code == results.status_code == 200
    output = tmp_path / "result.json"
    assert main(["run", str(fixture_path), "--output", str(output)]) == 0
    cli_result = json.loads(output.read_text(encoding="utf-8"))
    assert created.json()["result_content_hash"] == cli_result["result_content_hash"]
    assert created.json()["input_snapshot_hash"] == cli_result["input_snapshot_hash"]
    assert results.json()["result"] == cli_result["result"]


def test_api_queue_report_and_comparison() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    baseline = client.post("/api/v1/runs", json={"fixture": "PB-GOLDEN-CORE-01"})
    candidate = client.post("/api/v1/runs", json={"fixture": "PB-GOLDEN-QUEUE-01"})
    assert baseline.status_code == candidate.status_code == 201
    report = client.get(f"/api/v1/runs/{candidate.json()['run_id']}/report")
    assert report.status_code == 200
    assert "실제 지상 수신" in report.text
    comparison = client.post(
        "/api/v1/comparisons",
        json={
            "baseline_run_id": baseline.json()["run_id"],
            "candidate_run_id": candidate.json()["run_id"],
        },
    )
    assert comparison.status_code == 200
    rows = {row["metric"]: row for row in comparison.json()["metrics"]}
    assert rows["SCHEDULED_UNIQUE_CAPACITY_BYTES"]["absolute_delta"] == 0
    assert rows["SCHEDULED_UNIQUE_CAPACITY_BYTES"]["candidate_to_baseline_ratio"] == {
        "numerator": "1",
        "denominator": "1",
    }
    allocated = rows["PAYLOAD_ALLOCATED_BYTES"]
    assert allocated["baseline"] is None
    assert allocated["candidate"] == 145_000_000
    assert allocated["absolute_delta"] is None
    assert allocated["reason_codes"] == [{"code": "METRIC_NOT_COMPUTED_IN_BOTH_RUNS"}]


def test_api_errors_do_not_leak_sensitive_internals() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    for request in (
        {"fixture": "DOES-NOT-EXIST"},
        {"fixture": "PB-GOLDEN-CORE-01", "snapshot_id": "x"},
        {},
    ):
        response = client.post("/api/v1/runs", json=request)
        assert response.status_code == 422
        rendered = response.text.lower()
        assert not any(
            value in rendered
            for value in ("traceback", "password", "postgresql://", "c:\\users", "/home/")
        )
    missing = client.get("/api/v1/runs/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_unknown_rate_preserves_contacts_and_blocks_capacity(
    golden_snapshot: ScenarioSnapshot,
) -> None:
    station = golden_snapshot.stations[0]
    blocked_station = replace(
        station,
        capacity=replace(station.capacity, rate_unknown=True, rate_segments=()),
    )
    run = _service().run(
        replace(golden_snapshot, stations=(blocked_station, *golden_snapshot.stations[1:]))
    )
    assert run.status == "PARTIAL"
    assert run.result["metrics"]["geometric_contact_count"] == 16
    assert run.result["metrics"]["candidate_capacity_sum_bytes"] is None
    assert run.result["calculation_status"] == "BLOCKED"
    stages = {stage["stage_code"]: stage["status"] for stage in run.stages}
    assert stages["GEOMETRIC_ACCESS"] == "SUCCEEDED"
    assert stages["MODELED_CONTACT"] == "SUCCEEDED"
    assert stages["CANDIDATE_CAPACITY"] == "BLOCKED"
    unaffected = next(
        item for item in run.result["metrics"]["stations"] if item["station_key"] == "GS-B"
    )
    assert unaffected["candidate_capacity_sum_bytes"] == 160_000_000
    assert unaffected["calculation_status"] == "COMPUTED"


def test_partial_run_results_and_report_stay_retrievable() -> None:
    """AC-P0-24 / AC-44: a blocked later stage never hides the completed earlier stages."""
    client = TestClient(app, raise_server_exceptions=False)
    content = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "src"
            / "semantix_passbudget"
            / "fixtures"
            / "PB-GOLDEN-CORE-01.json"
        ).read_text(encoding="utf-8")
    )
    for station in content["stations"]:
        station["capacity"]["rate_unknown"] = True
        station["capacity"]["rate_segments"] = []
    created = client.post("/api/v1/runs", json={"snapshot": content})
    assert created.status_code == 201
    assert created.json()["status"] == "PARTIAL"
    run_id = created.json()["run_id"]
    results = client.get(f"/api/v1/runs/{run_id}/results")
    assert results.status_code == 200
    body = results.json()["result"]
    assert len(body["geometric_accesses"]) == 16
    assert body["metrics"]["candidate_capacity_sum_bytes"] is None
    report = client.get(f"/api/v1/runs/{run_id}/report")
    assert report.status_code == 200
    assert "BLOCKED" in report.text
