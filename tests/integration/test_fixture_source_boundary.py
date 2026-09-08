"""The HTTP API never reads a file named by the request; the CLI still may.

`fixture` is one string that used to reach one loader from both entry points, and that loader
fell back to reading a local path when the string was not a packaged identifier. On the CLI that
is the feature: the tool runs as the user, on the user's machine, against the user's own files.
Over HTTP the same string is supplied by whoever sent the request, so the same fallback let a
caller choose which file the server opens.

These cases fix the split in place: `load_public_fixture` for the network, `load_fixture_source`
for the CLI.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from semantix_passbudget.interfaces.api.app import app
from semantix_passbudget.interfaces.cli.main import main
from semantix_passbudget.interfaces.dto import (
    PUBLIC_FIXTURE_IDS,
    load_fixture_source,
    packaged_fixture_path,
)

#: A real, readable file on this host. If a path were accepted, this one would succeed, so it
#: separates "the path was rejected" from "the file happened not to exist".
REAL_FIXTURE_FILE = packaged_fixture_path("PB-GOLDEN-CORE-01")


def _client() -> TestClient:
    return TestClient(app)


def test_a_public_fixture_id_still_runs_over_http() -> None:
    response = _client().post("/api/v1/runs", json={"fixture": "PB-GOLDEN-QUEUE-01"})
    assert response.status_code == 201
    assert response.json()["run_id"]


@pytest.mark.parametrize("fixture_id", PUBLIC_FIXTURE_IDS)
def test_every_published_fixture_id_is_accepted(fixture_id: str) -> None:
    """The allowlist and the packaged files must not drift apart."""
    response = _client().post("/api/v1/runs", json={"fixture": fixture_id})
    assert response.status_code == 201, response.json()


def test_an_absolute_path_to_a_real_packaged_fixture_is_refused() -> None:
    assert REAL_FIXTURE_FILE.is_file(), "the test needs a file that would otherwise load"
    response = _client().post("/api/v1/runs", json={"fixture": str(REAL_FIXTURE_FILE)})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FIXTURE_PATH_NOT_ACCEPTED"


@pytest.mark.parametrize(
    "value",
    [
        "../fixtures/PB-GOLDEN-CORE-01.json",
        "..\\fixtures\\PB-GOLDEN-CORE-01.json",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "C:fixtures",
        "~/PB-GOLDEN-CORE-01.json",
        "fixtures/PB-GOLDEN-CORE-01.json",
        "./PB-GOLDEN-CORE-01",
        "%2e%2e/PB-GOLDEN-CORE-01",
    ],
)
def test_path_shaped_values_are_refused_whether_or_not_they_exist(value: str) -> None:
    response = _client().post("/api/v1/runs", json={"fixture": value})
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {
        "FIXTURE_PATH_NOT_ACCEPTED",
        "FIXTURE_NOT_FOUND",
    }


def test_an_unknown_plain_identifier_is_refused_as_a_missing_fixture() -> None:
    response = _client().post("/api/v1/runs", json={"fixture": "PB-GOLDEN-NOPE-99"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FIXTURE_NOT_FOUND"


def test_a_refusal_never_echoes_the_requested_path_to_the_body_or_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A rejection that repeats the path confirms what does and does not exist on the host."""
    requested = str(REAL_FIXTURE_FILE)
    with caplog.at_level(logging.DEBUG):
        response = _client().post("/api/v1/runs", json={"fixture": requested})
    assert response.status_code == 422
    rendered = response.text
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for haystack in (rendered, logged):
        assert requested not in haystack
        assert REAL_FIXTURE_FILE.name not in haystack
        assert str(REAL_FIXTURE_FILE.parent) not in haystack


def test_the_cli_still_accepts_an_explicit_local_fixture_file(tmp_path: Path) -> None:
    """The CLI is a local tool run by the file's owner, so a path stays a legitimate input."""
    local = tmp_path / "local-copy.json"
    local.write_text(REAL_FIXTURE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_fixture_source(str(local)).fixture_id == "PB-GOLDEN-CORE-01"

    output = tmp_path / "result.json"
    assert main(["run", str(local), "--output", str(output)]) == 0
    envelope = json.loads(output.read_text(encoding="utf-8"))
    assert envelope["result"]["metrics"]["scheduled_unique_capacity_bytes"] == 560_000_000


def test_the_execution_strategy_belongs_to_the_scenario_not_to_the_request() -> None:
    """A run names an immutable input; it does not reach in and change one.

    Putting `execution_strategy` on the request would let one stored snapshot answer two
    different questions under one identity. The strict DTO refuses the field, and the strategy
    is set where it is a property of the scenario -- which is why the two runs have different
    input hashes rather than one hash with two meanings.
    """
    client = _client()
    refused = client.post(
        "/api/v1/runs",
        json={"fixture": "PB-GOLDEN-QUEUE-01", "execution_strategy": "BOUNDED_APPROXIMATE"},
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "INVALID_REQUEST"

    scenario = json.loads(packaged_fixture_path("PB-GOLDEN-QUEUE-01").read_text(encoding="utf-8"))
    scenario["execution_strategy"] = "BOUNDED_APPROXIMATE"
    created = client.post("/api/v1/runs", json={"snapshot": scenario})
    assert created.status_code == 201, created.text
    results = client.get(f"/api/v1/runs/{created.json()['run_id']}/results").json()
    assert results["result"]["optimization"] == {
        "execution_strategy": "BOUNDED_APPROXIMATE",
        "optimization_status": "APPROXIMATE",
        "globally_optimal": False,
        "optimality_gap": None,
        "algorithm_revision": "QUEUE_AWARE_BOUNDED_POLICY_FAMILY_V2",
    }

    exact = client.post("/api/v1/runs", json={"fixture": "PB-GOLDEN-QUEUE-01"})
    assert exact.status_code == 201
    assert exact.json()["input_snapshot_hash"] != created.json()["input_snapshot_hash"]
