"""Contract test for the read-only scenario-revision content endpoint (FE-GAP-01).

The frontend needs to read a saved scenario's input body back after a refresh. This endpoint reuses
the repository revision lookup and returns the stored FixtureDTO content; it changes no domain rule,
schema, canonical hash or golden output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from semantix_passbudget.interfaces.api.app import app
from semantix_passbudget.interfaces.dto import parse_fixture_content

FIXTURES = Path(__file__).resolve().parents[2] / "src" / "semantix_passbudget" / "fixtures"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def orb_content() -> dict[str, Any]:
    return json.loads((FIXTURES / "PB-GOLDEN-ORB-01.json").read_text(encoding="utf-8"))


def test_revision_content_roundtrips_the_saved_scenario(
    client: TestClient, orb_content: dict[str, Any]
) -> None:
    created = client.post(
        "/api/v1/scenarios",
        json={"stable_key": "SC-CONTENT-01", "name": "content roundtrip", "content": orb_content},
    )
    assert created.status_code == 201, created.text
    scenario_id = created.json()["scenario_id"]
    revision_id = created.json()["revisions"][0]["revision_id"]

    fetched = client.get(f"/api/v1/scenario-revisions/{revision_id}/content")
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert body["scenario_id"] == scenario_id
    assert body["revision_id"] == revision_id
    # The stored content is the executable input: it re-parses and validates, and names the fixture.
    assert body["content"]["fixture_id"] == "PB-GOLDEN-ORB-01"
    parse_fixture_content(body["content"]).to_domain().validate()


def test_unknown_revision_is_404_without_internal_detail(client: TestClient) -> None:
    response = client.get("/api/v1/scenario-revisions/does-not-exist/content")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "SCENARIO_REVISION_NOT_FOUND"
    # The response must not echo a path or database identifier.
    assert "does-not-exist" not in error["message"]


def test_content_body_carries_no_secret_or_path_fields(
    client: TestClient, orb_content: dict[str, Any]
) -> None:
    created = client.post(
        "/api/v1/scenarios",
        json={"stable_key": "SC-CONTENT-02", "name": "boundary", "content": orb_content},
    )
    revision_id = created.json()["revisions"][0]["revision_id"]
    body = client.get(f"/api/v1/scenario-revisions/{revision_id}/content").json()
    assert set(body.keys()) == {
        "revision_id",
        "scenario_id",
        "revision_no",
        "lifecycle_status",
        "schema_version",
        "content",
    }
