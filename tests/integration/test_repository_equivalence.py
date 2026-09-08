"""Every repository tier must be indistinguishable from the others.

The same computed run is written to and read back from each available tier and compared on
everything that carries meaning: the three hashes, the stage list, the typed persisted rows and
their canonical hash, and the absence of invented orbit or elevation data.

The in-memory and SQLite tiers always run. The PostgreSQL tier joins only when a disposable
`PASSBUDGET_TEST_DATABASE_URL` is configured, and is skipped — never silently passed — otherwise.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.orbit.provider import OrbitContactProvider
from semantix_passbudget.adapters.sqlite.repository import (
    SqlitePersistenceError,
    SqliteRunRepository,
)
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.domain.canonical import semantic_hash
from semantix_passbudget.interfaces.dto import PUBLIC_FIXTURE_IDS, load_fixture_source
from semantix_passbudget.ports.persisted_rows import result_rows, rows_hash, rows_view
from semantix_passbudget.ports.run_repository import RunRepository, StoredRun
from tests.integration.postgres_guard import TEST_URL_ENV, postgres_capable_fixtures

POSTGRES_CAPABLE_FIXTURES = postgres_capable_fixtures()


def _compute(fixture_id: str) -> StoredRun:
    """One pure calculation, shared by every tier. No repository takes part in it."""
    service = RunScenarioService(
        SyntheticContactProvider(),
        InMemoryRunRepository(),
        orbit_provider=OrbitContactProvider(),
    )
    return service.run(load_fixture_source(fixture_id).to_domain())


def _view(stored: StoredRun) -> dict[str, Any]:
    """The persisted row view, whichever way the tier supplied it."""
    if stored.persisted_rows is not None:
        return rows_view(stored.persisted_rows)
    return rows_view(result_rows(stored.result))


def _hash(stored: StoredRun) -> str:
    if stored.persisted_rows is not None:
        return rows_hash(stored.persisted_rows)
    return rows_hash(result_rows(stored.result))


@pytest.fixture
def memory_repository() -> InMemoryRunRepository:
    return InMemoryRunRepository()


@pytest.fixture
def sqlite_repository(sqlite_path: Path) -> SqliteRunRepository:
    return SqliteRunRepository(sqlite_path)


@pytest.fixture
def postgres_repository() -> Iterator[Any]:
    if not (os.getenv(TEST_URL_ENV) or "").strip():
        pytest.skip(f"{TEST_URL_ENV} is not configured")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from semantix_passbudget.adapters.postgres.repository import PostgresRunRepository
    from tests.integration.postgres_guard import require_disposable_url

    url = require_disposable_url()
    root = Path(__file__).resolve().parents[2]
    engine = create_engine(url, hide_parameters=True, future=True)
    with engine.connect() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS passbudget CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
        connection.commit()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    yield PostgresRunRepository(engine)
    engine.dispose()


def _tiers(request: pytest.FixtureRequest) -> dict[str, RunRepository]:
    tiers: dict[str, RunRepository] = {
        "memory": request.getfixturevalue("memory_repository"),
        "sqlite": request.getfixturevalue("sqlite_repository"),
    }
    if (os.getenv(TEST_URL_ENV) or "").strip():
        tiers["postgresql"] = request.getfixturevalue("postgres_repository")
    return tiers


@pytest.mark.parametrize("fixture_id", PUBLIC_FIXTURE_IDS)
def test_memory_and_sqlite_agree_on_every_stored_fact(
    fixture_id: str, memory_repository: InMemoryRunRepository, sqlite_path: Path
) -> None:
    run = _compute(fixture_id)
    sqlite_repository = SqliteRunRepository(sqlite_path)
    memory_repository.add(run)
    sqlite_repository.add(run)
    from_memory = memory_repository.get(run.run_id)
    from_sqlite = sqlite_repository.get(run.run_id)
    assert from_memory is not None and from_sqlite is not None

    for stored in (from_memory, from_sqlite):
        assert stored.input_snapshot_hash == run.input_snapshot_hash
        assert stored.result_content_hash == run.result_content_hash
        assert stored.run_record_hash == run.run_record_hash
        assert stored.status == run.status
        assert stored.stages == run.stages
    assert _view(from_memory) == _view(from_sqlite)
    assert _hash(from_memory) == _hash(from_sqlite)
    # The rendered result document survives the local tier byte for byte.
    assert from_sqlite.result == run.result
    assert semantic_hash("RESULT", from_sqlite.result) == run.result_content_hash


@pytest.mark.parametrize("fixture_id", POSTGRES_CAPABLE_FIXTURES)
def test_every_available_tier_agrees(fixture_id: str, request: pytest.FixtureRequest) -> None:
    run = _compute(fixture_id)
    tiers = _tiers(request)
    views: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for name, repository in tiers.items():
        repository.add(run)
        stored = repository.get(run.run_id)
        assert stored is not None, name
        assert stored.input_snapshot_hash == run.input_snapshot_hash, name
        assert stored.result_content_hash == run.result_content_hash, name
        assert stored.run_record_hash == run.run_record_hash, name
        assert stored.stages == run.stages, name
        views[name] = _view(stored)
        hashes[name] = _hash(stored)
    assert len(set(hashes.values())) == 1, hashes
    reference = views["memory"]
    for name, view in views.items():
        assert view == reference, name


def test_input_order_permutation_reaches_the_same_stored_rows(sqlite_path: Path) -> None:
    snapshot = load_fixture_source("PB-GOLDEN-QUEUE-01").to_domain()
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
    repository = SqliteRunRepository(sqlite_path)
    repository.add(baseline)
    repository.add(permuted)
    stored_baseline = repository.get(baseline.run_id)
    stored_permuted = repository.get(permuted.run_id)
    assert stored_baseline is not None and stored_permuted is not None
    assert stored_baseline.input_snapshot_hash == stored_permuted.input_snapshot_hash
    assert stored_baseline.result_content_hash == stored_permuted.result_content_hash
    assert _view(stored_baseline) == _view(stored_permuted)


def test_same_semantic_input_shares_one_snapshot_row(sqlite_path: Path) -> None:
    first = _compute("PB-GOLDEN-HORIZON-01")
    second = _compute("PB-GOLDEN-HORIZON-01")
    assert first.input_snapshot_hash == second.input_snapshot_hash
    assert first.run_id != second.run_id
    repository = SqliteRunRepository(sqlite_path)
    repository.add(first)
    repository.add(second)
    with repository._connection() as connection:
        snapshots = connection.execute(
            "SELECT count(*) AS n FROM input_snapshot WHERE content_sha256 = ?",
            (first.input_snapshot_hash,),
        ).fetchone()["n"]
        revisions = connection.execute("SELECT count(*) AS n FROM scenario_revision").fetchone()[
            "n"
        ]
    assert snapshots == 1
    assert revisions == 1


def test_terminal_run_cannot_be_rewritten_in_any_tier(
    memory_repository: InMemoryRunRepository, sqlite_path: Path
) -> None:
    run = _compute("PB-GOLDEN-CORE-01")
    sqlite_repository = SqliteRunRepository(sqlite_path)
    memory_repository.add(run)
    sqlite_repository.add(run)
    with pytest.raises(ValueError):
        memory_repository.add(run)
    with pytest.raises(SqlitePersistenceError):
        sqlite_repository.add(run)


def test_synthetic_rows_carry_no_orbit_revision_or_elevation(sqlite_path: Path) -> None:
    run = _compute("PB-GOLDEN-CORE-01")
    repository = SqliteRunRepository(sqlite_path)
    repository.add(run)
    with repository._connection() as connection:
        revision = connection.execute(
            "SELECT contact_source, orbit_revision_id, synthetic_contact_provider_revision"
            " FROM scenario_revision"
        ).fetchone()
        invented = connection.execute(
            "SELECT count(*) AS n FROM geometric_access"
            " WHERE contact_source = 'SYNTHETIC_INJECTED'"
            " AND (maximum_elevation_udeg IS NOT NULL OR maximum_elevation_at_us IS NOT NULL)"
        ).fetchone()["n"]
    assert revision["contact_source"] == "SYNTHETIC_INJECTED"
    assert revision["orbit_revision_id"] is None
    assert revision["synthetic_contact_provider_revision"] == "SYN-CONTACT-01-R1"
    assert invented == 0


def test_utc_microseconds_survive_the_local_round_trip(sqlite_path: Path) -> None:
    run = _compute("PB-GOLDEN-QUEUE-01")
    repository = SqliteRunRepository(sqlite_path)
    repository.add(run)
    stored = repository.get(run.run_id)
    assert stored is not None and stored.persisted_rows is not None
    allocations = {
        row["payload_key"]: row
        for row in stored.persisted_rows.allocations
        if row["scheduled_session_stable_key"] == "scheduled/A1"
    }
    assert allocations["P-ALERT"]["ended_at"] == "2027-01-01T00:11:00.800000Z"
    assert allocations["P-THUMB"]["ended_at"] == "2027-01-01T00:11:16.000000Z"
    assert allocations["P-MASK"]["ended_at"] == "2027-01-01T00:12:20.000000Z"
    assert allocations["P-ORIGINAL"]["ended_at"] == "2027-01-01T00:19:00.000000Z"


def test_exact_byte_values_are_stored_as_text_not_as_integers(sqlite_path: Path) -> None:
    """SQLite INTEGER is signed 64-bit; the byte domain is not. Text keeps it exact."""
    run = _compute("PB-GOLDEN-QUEUE-01")
    repository = SqliteRunRepository(sqlite_path)
    repository.add(run)
    with repository._connection() as connection:
        rows = connection.execute(
            "SELECT typeof(capacity_bytes) AS kind, capacity_bytes FROM candidate_session"
        ).fetchall()
        occupancy = connection.execute(
            "SELECT typeof(logical_size_bytes) AS kind FROM scenario_payload"
        ).fetchall()
    assert rows and all(row["kind"] == "text" for row in rows)
    assert occupancy and all(row["kind"] == "text" for row in occupancy)
    assert "60000000" in {row["capacity_bytes"] for row in rows}


def test_the_stored_snapshot_payload_is_canonical_and_json_safe(sqlite_path: Path) -> None:
    """The inspection copy must be the canonical structure, not a Python repr.

    `snapshot_semantics` returns real `Fraction` and `UtcInstant` objects. Neither can cross a
    JSON boundary: PostgreSQL's `jsonb` binding raises, and coercing with `str()` would store
    `'3/4'` and `'UtcInstant(microseconds=...)'` instead of the canonical form. Both adapters
    therefore store `canonical_object(payload)`, which is byte-identical to what the hash covers.
    """
    import json

    from semantix_passbudget.domain.canonical import canonical_bytes, canonical_object

    run = _compute("PB-GOLDEN-QUEUE-01")
    payload = run.input_snapshot_payload
    with pytest.raises(TypeError):
        json.dumps(payload)  # the raw graph is deliberately not JSON-safe
    canonical = canonical_object(payload)
    json.dumps(canonical)  # the canonical form always is

    repository = SqliteRunRepository(sqlite_path)
    repository.add(run)
    with repository._connection() as connection:
        row = connection.execute(
            "SELECT canonical_payload, canonical_bytes, content_sha256 FROM input_snapshot"
        ).fetchone()
    stored = json.loads(row["canonical_payload"])
    assert stored == canonical
    assert bytes(row["canonical_bytes"]) == canonical_bytes(payload)
    assert row["content_sha256"] == run.input_snapshot_hash
    # Spot-check the two types that used to be corrupted.
    assert stored["stations"][0]["capacity"]["rate_segments"][0]["rate"] == {
        "d": "1",
        "n": "500000",
    }
    assert stored["payloads"][0]["ready_at"] == "2027-01-01T00:05:00.000000Z"
