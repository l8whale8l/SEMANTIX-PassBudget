"""The API on its default tier: SQLite, surviving a process restart.

The module-level application is already SQLite-backed (the test sandbox redirects
`PASSBUDGET_DATA_DIR`), so these cases check the behaviour that only persistence can give:
a run written by one process is readable, byte for byte, by the next one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from semantix_passbudget.application.composition import (
    SQLITE_PATH_ENV,
    build_application,
)
from semantix_passbudget.interfaces.api.app import app, application
from semantix_passbudget.interfaces.cli.main import main
from semantix_passbudget.interfaces.dto import load_fixture_source


def test_the_default_api_tier_is_sqlite() -> None:
    assert application.persistence == "sqlite"
    assert application.database_path is not None
    assert application.database_path.endswith(".sqlite3")


def test_health_reports_the_tier_and_no_location() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    body = client.get("/health").json()
    assert body == {"status": "ok", "persistence": "sqlite"}
    rendered = json.dumps(body).lower()
    for forbidden in ("appdata", "/home/", "c:\\", ".sqlite3", "postgresql://"):
        assert forbidden not in rendered


def test_a_run_survives_a_restart_with_identical_hashes_and_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = tmp_path / "restart.sqlite3"
    monkeypatch.setenv(SQLITE_PATH_ENV, str(database))

    first = build_application(seed_presets=False, default_persistence="sqlite")
    assert first.persistence == "sqlite"
    run = first.runs.run(load_fixture_source("PB-GOLDEN-QUEUE-01").to_domain())

    # A second process opens the same file. Nothing is carried over in memory.
    second = build_application(seed_presets=False, default_persistence="sqlite")
    reloaded = second.runs.get(run.run_id)
    assert reloaded is not None
    assert reloaded.input_snapshot_hash == run.input_snapshot_hash
    assert reloaded.result_content_hash == run.result_content_hash
    assert reloaded.run_record_hash == run.run_record_hash
    assert reloaded.stages == run.stages
    assert reloaded.result == run.result
    assert reloaded.result["metrics"]["scheduled_unique_capacity_bytes"] == 560_000_000


def test_api_run_results_and_report_come_from_the_local_store() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    created = client.post("/api/v1/runs", json={"fixture": "PB-GOLDEN-QUEUE-01"})
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    results = client.get(f"/api/v1/runs/{run_id}/results")
    assert results.status_code == 200
    assert results.json()["result"]["metrics"]["payload_allocated_bytes"] == 145_000_000
    report = client.get(f"/api/v1/runs/{run_id}/report")
    assert report.status_code == 200
    assert "실제 지상 수신" in report.text


def test_cli_persist_and_show_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(SQLITE_PATH_ENV, str(tmp_path / "cli.sqlite3"))
    output = tmp_path / "core.json"
    assert main(["run", "PB-GOLDEN-CORE-01", "--output", str(output), "--persist"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["persistent_tier"] == "sqlite"
    run_id = printed["run_id"]

    assert main(["show", run_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["run_id"] == run_id
    assert shown["result_content_hash"] == printed["result_content_hash"]
    assert shown["input_snapshot_hash"] == printed["input_snapshot_hash"]

    assert main(["show", "00000000-0000-0000-0000-000000000000"]) == 2
    missing = json.loads(capsys.readouterr().out)
    assert missing["error"]["code"] == "RUN_NOT_FOUND"


def test_cli_calculation_commands_touch_no_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`run` without `--persist` must not create the local database file."""
    database = tmp_path / "untouched.sqlite3"
    monkeypatch.setenv(SQLITE_PATH_ENV, str(database))
    output = tmp_path / "core.json"
    assert main(["run", "PB-GOLDEN-CORE-01", "--output", str(output)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["persistent_tier"] == "memory"
    assert main(["validate", "PB-GOLDEN-CORE-01"]) == 0
    capsys.readouterr()
    assert main(["verify-golden"]) == 0
    capsys.readouterr()
    assert not database.exists()


def test_cli_where_reports_the_resolved_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(SQLITE_PATH_ENV, str(tmp_path / "where.sqlite3"))
    assert main(["where"]) == 0
    described = json.loads(capsys.readouterr().out)
    assert described["persistent_tier"] == "sqlite"
    assert described["calculation_default"] == "memory (no database)"
    assert described["database_location"] == str(tmp_path / "where.sqlite3")
