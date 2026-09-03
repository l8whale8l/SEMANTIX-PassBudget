"""SQLite clean install, idempotent re-open, and the constraints the schema promises.

None of this needs PostgreSQL, Docker or a network. It is the default local tier, so it is a
plain unmarked test that always runs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.sqlite import schema
from semantix_passbudget.adapters.sqlite.repository import SqliteRunRepository
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.interfaces.dto import load_fixture_source

EXPECTED_TABLES = 22


def test_clean_install_creates_the_whole_schema(sqlite_path: Path) -> None:
    assert not sqlite_path.exists()
    connection = schema.open_database(sqlite_path)
    try:
        assert schema.current_version(connection) == schema.SCHEMA_VERSION
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert len(tables) == EXPECTED_TABLES
        assert {"scenario_run", "run_result", "geometric_access", "run_result_document"} <= tables
    finally:
        connection.close()
    assert sqlite_path.exists()


def test_reopening_an_existing_database_is_a_no_op(sqlite_path: Path) -> None:
    first = schema.open_database(sqlite_path)
    applied = schema.migrate(first).applied_at_us
    first.close()
    second = schema.open_database(sqlite_path)
    try:
        state = schema.migrate(second)
        assert state.version == schema.SCHEMA_VERSION
        # A no-op migration must not rewrite the recorded application time.
        assert state.applied_at_us == applied
    finally:
        second.close()


def test_a_newer_file_is_refused_rather_than_downgraded(sqlite_path: Path) -> None:
    connection = schema.open_database(sqlite_path)
    connection.execute(
        "UPDATE schema_version SET version = ? WHERE id = 1", (schema.SCHEMA_VERSION + 1,)
    )
    connection.close()
    reopened = schema.connect(sqlite_path)
    try:
        with pytest.raises(schema.SqliteSchemaError) as caught:
            schema.migrate(reopened)
        assert "Upgrade the application" in str(caught.value)
    finally:
        reopened.close()


def test_foreign_keys_are_enforced_on_every_connection(sqlite_path: Path) -> None:
    connection = schema.open_database(sqlite_path)
    try:
        assert int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO scenario_revision (id, scenario_id, revision_no, lifecycle_status,"
                " schema_version, decision_question, analysis_start_us, analysis_end_us,"
                " analysis_mode, contact_source, synthetic_contact_provider_revision,"
                " spacecraft_key, storage_mode, overlap_objective_revision,"
                " tie_break_profile_revision, event_order_revision, time_quantization_revision,"
                " display_format_revision, semantic_hash)"
                " VALUES ('r', 'missing-scenario', 1, 'DRAFT', 'v', 'q', 0, 1, 'NETWORK_ONLY',"
                " 'SYNTHETIC_INJECTED', 'SYN', 'SC', 'DISABLED', 'o', 't', 'e', 'q2', 'd', ?)",
                ("0" * 64,),
            )
    finally:
        connection.close()


def test_enum_columns_reject_an_unknown_code(sqlite_path: Path) -> None:
    connection = schema.open_database(sqlite_path)
    try:
        connection.execute(
            "INSERT INTO scenario (id, stable_key, name, description, is_preset, created_at_us)"
            " VALUES ('s', 'SC-1', 'n', NULL, 1, 0)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO scenario_revision (id, scenario_id, revision_no, lifecycle_status,"
                " schema_version, decision_question, analysis_start_us, analysis_end_us,"
                " analysis_mode, contact_source, synthetic_contact_provider_revision,"
                " spacecraft_key, storage_mode, overlap_objective_revision,"
                " tie_break_profile_revision, event_order_revision, time_quantization_revision,"
                " display_format_revision, semantic_hash)"
                " VALUES ('r', 's', 1, 'DRAFT', 'v', 'q', 0, 1, 'SOMETHING_ELSE',"
                " 'SYNTHETIC_INJECTED', 'SYN', 'SC', 'DISABLED', 'o', 't', 'e', 'q2', 'd', ?)",
                ("0" * 64,),
            )
    finally:
        connection.close()


def test_orbit_derived_access_still_requires_a_maximum_elevation(sqlite_path: Path) -> None:
    """The ADR-0002 contract is mirrored, not weakened, in the local tier."""
    connection = schema.open_database(sqlite_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO geometric_access (result_id, scenario_station_id, true_aos_us,"
                " true_los_us, clipped_start_us, clipped_end_us, contact_source)"
                " VALUES ('g', 'st', 0, 10, 0, 10, 'ORBIT_DERIVED')"
            )
    finally:
        connection.close()


def test_a_terminal_run_row_cannot_be_updated_or_deleted(sqlite_path: Path) -> None:
    service = RunScenarioService(SyntheticContactProvider(), InMemoryRunRepository())
    run = service.run(load_fixture_source("PB-GOLDEN-CORE-01").to_domain())
    repository = SqliteRunRepository(sqlite_path)
    repository.add(run)
    connection = schema.connect(sqlite_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE scenario_run SET status = 'FAILED' WHERE id = ?", (run.run_id,)
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM scenario_run WHERE id = ?", (run.run_id,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE run_result_document SET document = '{}' WHERE run_id = ?", (run.run_id,)
            )
    finally:
        connection.close()


def test_the_ddl_ships_with_the_package_or_the_checkout() -> None:
    directory = schema.ddl_dir()
    assert (directory / "schema_v1.sql").is_file(), directory


def test_exact_integer_columns_reject_a_non_decimal_value(sqlite_path: Path) -> None:
    connection = schema.open_database(sqlite_path)
    try:
        connection.execute(
            "INSERT INTO scenario (id, stable_key, name, description, is_preset, created_at_us)"
            " VALUES ('s', 'SC-1', 'n', NULL, 1, 0)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO scenario_revision (id, scenario_id, revision_no, lifecycle_status,"
                " schema_version, decision_question, analysis_start_us, analysis_end_us,"
                " analysis_mode, contact_source, synthetic_contact_provider_revision,"
                " spacecraft_key, storage_mode, physical_capacity_bytes, protected_reserve_bytes,"
                " initial_nonqueue_bytes, reserve_enforcement, storage_admission_policy,"
                " reclaim_granularity, release_trigger, delivery_assumption,"
                " overlap_objective_revision, tie_break_profile_revision, event_order_revision,"
                " time_quantization_revision, display_format_revision, semantic_hash)"
                " VALUES ('r', 's', 1, 'DRAFT', 'v', 'q', 0, 1, 'QUEUE_AWARE',"
                " 'SYNTHETIC_INJECTED', 'SYN', 'SC', 'ENABLED', '2.0e8', '0', '0', 'HARD',"
                " 'REJECT_NEW', 'OBJECT', 'NEVER', 'NONE', 'o', 't', 'e', 'q2', 'd', ?)",
                ("0" * 64,),
            )
    finally:
        connection.close()


def test_a_byte_count_above_int64_survives_the_round_trip(sqlite_path: Path) -> None:
    """The reason bytes are text: `numeric(20,0)` does not fit a signed 64-bit integer."""
    huge = 10**20 - 1
    assert huge > 2**63 - 1
    connection = schema.open_database(sqlite_path)
    try:
        connection.execute(
            "INSERT INTO scenario (id, stable_key, name, description, is_preset, created_at_us)"
            " VALUES ('s', 'SC-1', 'n', NULL, 1, 0)"
        )
        connection.execute(
            "INSERT INTO scenario_revision (id, scenario_id, revision_no, lifecycle_status,"
            " schema_version, decision_question, analysis_start_us, analysis_end_us,"
            " analysis_mode, contact_source, synthetic_contact_provider_revision,"
            " spacecraft_key, storage_mode, physical_capacity_bytes, protected_reserve_bytes,"
            " initial_nonqueue_bytes, reserve_enforcement, storage_admission_policy,"
            " reclaim_granularity, release_trigger, delivery_assumption,"
            " overlap_objective_revision, tie_break_profile_revision, event_order_revision,"
            " time_quantization_revision, display_format_revision, semantic_hash)"
            " VALUES ('r', 's', 1, 'DRAFT', 'v', 'q', 0, 1, 'QUEUE_AWARE',"
            " 'SYNTHETIC_INJECTED', 'SYN', 'SC', 'ENABLED', ?, '0', '0', 'HARD',"
            " 'REJECT_NEW', 'OBJECT', 'NEVER', 'NONE', 'o', 't', 'e', 'q2', 'd', ?)",
            (str(huge), "0" * 64),
        )
        stored = connection.execute(
            "SELECT physical_capacity_bytes, typeof(physical_capacity_bytes) AS kind"
            " FROM scenario_revision"
        ).fetchone()
        assert stored["kind"] == "text"
        assert int(stored["physical_capacity_bytes"]) == huge
    finally:
        connection.close()
