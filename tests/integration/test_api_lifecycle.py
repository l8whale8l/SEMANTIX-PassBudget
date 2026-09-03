"""P0 data-lifecycle endpoints: preset -> profile -> scenario -> snapshot -> run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from semantix_passbudget.interfaces.api.app import app

FIXTURES = Path(__file__).resolve().parents[2] / "src" / "semantix_passbudget" / "fixtures"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def core_content() -> dict[str, Any]:
    return json.loads((FIXTURES / "PB-GOLDEN-CORE-01.json").read_text(encoding="utf-8"))


def test_presets_list_seeded_public_fixtures(client: TestClient) -> None:
    response = client.get("/api/v1/presets")
    assert response.status_code == 200
    body = response.json()
    scenario_keys = {item["stable_key"] for item in body["scenarios"]}
    assert {"PB-GOLDEN-CORE-01", "PB-GOLDEN-QUEUE-01", "PB-GOLDEN-OVERLAP-01"} <= scenario_keys
    assert body["profiles"]["COMMUNICATION"], "communication presets are decomposed from fixtures"
    assert all(item["current_revision_id"] for item in body["profiles"]["GROUND_STATION"])


def test_profile_lifecycle_publishes_an_immutable_revision(client: TestClient) -> None:
    created = client.post(
        "/api/v1/profiles",
        json={
            "stable_key": "TEST-GS-01",
            "kind": "GROUND_STATION",
            "name": "Test ground station",
        },
    )
    assert created.status_code == 201
    profile_id = created.json()["profile_id"]
    assert created.json()["current_revision_id"] is None

    revision = client.post(
        f"/api/v1/profiles/{profile_id}/revisions",
        json={
            "label": "r1",
            "payload": {
                "latitude_udeg": None,
                "longitude_udeg": None,
                "ellipsoidal_height_mm": None,
                "rx_resource_key": "TEST-GS-01-RX1",
            },
        },
    )
    assert revision.status_code == 201
    assert revision.json()["lifecycle_status"] == "DRAFT"
    revision_id = revision.json()["revision_id"]

    published = client.post(f"/api/v1/profile-revisions/{revision_id}/publish")
    assert published.status_code == 200
    assert published.json()["lifecycle_status"] == "PUBLISHED"
    assert published.json()["semantic_hash"]

    again = client.post(f"/api/v1/profile-revisions/{revision_id}/publish")
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "REVISION_ALREADY_PUBLISHED"

    fetched = client.get(f"/api/v1/profiles/{profile_id}")
    assert fetched.status_code == 200
    assert fetched.json()["current_revision_id"] == revision_id
    assert [item["revision_no"] for item in fetched.json()["revisions"]] == [1]


def test_scenario_lifecycle_snapshot_and_run(
    client: TestClient, core_content: dict[str, Any]
) -> None:
    created = client.post(
        "/api/v1/scenarios",
        json={
            "stable_key": "TEST-SCENARIO-01",
            "name": "Lifecycle regression",
            "content": core_content,
        },
    )
    assert created.status_code == 201
    scenario_id = created.json()["scenario_id"]
    draft_id = created.json()["revisions"][0]["revision_id"]

    # A draft cannot be promoted to an executable snapshot.
    rejected = client.post(f"/api/v1/scenario-revisions/{draft_id}/snapshots")
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "REVISION_NOT_PUBLISHED"

    published = client.post(f"/api/v1/scenario-revisions/{draft_id}/publish")
    assert published.status_code == 200
    assert published.json()["lifecycle_status"] == "PUBLISHED"

    snapshot = client.post(f"/api/v1/scenario-revisions/{draft_id}/snapshots")
    assert snapshot.status_code == 201
    snapshot_id = snapshot.json()["snapshot_id"]
    assert snapshot.json()["validation_status"] == "VALID"
    assert snapshot.json()["canonicalization_revision"] == "PB-C14N-JSON-V1"

    # The same published revision promotes to a snapshot with the same canonical hash.
    again = client.post(f"/api/v1/scenario-revisions/{draft_id}/snapshots")
    assert again.json()["input_snapshot_hash"] == snapshot.json()["input_snapshot_hash"]
    assert again.json()["snapshot_id"] != snapshot_id

    run = client.post("/api/v1/runs", json={"snapshot_id": snapshot_id})
    assert run.status_code == 201
    assert run.json()["status"] == "SUCCEEDED"
    results = client.get(f"/api/v1/runs/{run.json()['run_id']}/results")
    assert results.json()["result"]["metrics"]["scheduled_unique_capacity_bytes"] == 560_000_000

    scenario = client.get(f"/api/v1/scenarios/{scenario_id}")
    assert scenario.status_code == 200
    assert run.json()["run_id"] in scenario.json()["recent_run_ids"]


def test_new_revision_from_base_and_clone_are_independent(
    client: TestClient, core_content: dict[str, Any]
) -> None:
    created = client.post(
        "/api/v1/scenarios",
        json={
            "stable_key": "TEST-SCENARIO-02",
            "name": "Clone regression",
            "content": core_content,
        },
    )
    scenario_id = created.json()["scenario_id"]
    base_id = created.json()["revisions"][0]["revision_id"]
    client.post(f"/api/v1/scenario-revisions/{base_id}/publish")

    derived = client.post(
        f"/api/v1/scenarios/{scenario_id}/revisions",
        json={"based_on_revision_id": base_id},
    )
    assert derived.status_code == 201
    assert derived.json()["revision_no"] == 2
    assert derived.json()["lifecycle_status"] == "DRAFT"
    assert derived.json()["based_on_revision_id"] == base_id

    clone = client.post(
        f"/api/v1/scenario-revisions/{base_id}/clone",
        json={"stable_key": "TEST-SCENARIO-02-VARIANT", "name": "Variant"},
    )
    assert clone.status_code == 201
    assert clone.json()["scenario_id"] != scenario_id
    assert clone.json()["revisions"][0]["lifecycle_status"] == "DRAFT"

    # Publishing the clone leaves the source head's pointer untouched.
    source = client.get(f"/api/v1/scenarios/{scenario_id}")
    assert source.json()["current_revision_id"] == base_id


def test_snapshot_promotion_rejects_an_invalid_published_revision(
    client: TestClient, core_content: dict[str, Any]
) -> None:
    broken = dict(core_content)
    broken["stations"] = [
        {
            **core_content["stations"][0],
            "capacity": {
                **core_content["stations"][0]["capacity"],
                "fixed_capacity_bytes": 1,
            },
        },
        *core_content["stations"][1:],
    ]
    created = client.post(
        "/api/v1/scenarios",
        json={
            "stable_key": "TEST-SCENARIO-03",
            "name": "Conflicting capacity inputs",
            "content": broken,
        },
    )
    assert created.status_code == 201
    revision_id = created.json()["revisions"][0]["revision_id"]
    client.post(f"/api/v1/scenario-revisions/{revision_id}/publish")
    promoted = client.post(f"/api/v1/scenario-revisions/{revision_id}/snapshots")
    assert promoted.status_code == 422
    error = promoted.json()["error"]
    assert error["code"] == "INPUT_FACTOR_CONFLICT"
    assert error["affected_branches"] == ["capacity", "schedule"]
    assert error["details"]["snapshot_promotion"] == "REJECTED"


def test_missing_resources_return_404_without_internal_detail(client: TestClient) -> None:
    unknown = "00000000-0000-0000-0000-000000000000"
    for path in (
        f"/api/v1/profiles/{unknown}",
        f"/api/v1/scenarios/{unknown}",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"].endswith("NOT_FOUND")
    response = client.post("/api/v1/runs", json={"snapshot_id": unknown})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SNAPSHOT_NOT_FOUND"
    rendered = response.text.lower()
    assert not any(
        value in rendered for value in ("traceback", "postgresql://", "c:\\users", "/home/")
    )


def test_duplicate_stable_key_is_rejected(client: TestClient) -> None:
    body = {"stable_key": "TEST-DUP-01", "kind": "POLICY", "name": "Duplicate"}
    assert client.post("/api/v1/profiles", json=body).status_code == 201
    duplicate = client.post("/api/v1/profiles", json=body)
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "DUPLICATE_STABLE_KEY"
