"""Live PostgreSQL 16 persistence round trip.

Runs only when `PASSBUDGET_TEST_DATABASE_URL` names a disposable PostgreSQL 16+ database. Without
one the case is skipped, and a skip is not evidence: offline row-mapping coverage lives in
`tests/unit/test_persistence_mapping.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from semantix_passbudget.adapters.memory_repository import InMemoryRunRepository
from semantix_passbudget.adapters.orbit.provider import OrbitContactProvider
from semantix_passbudget.adapters.postgres.repository import (
    PersistenceError,
    PostgresRunRepository,
)
from semantix_passbudget.adapters.synthetic_contact import SyntheticContactProvider
from semantix_passbudget.application.service import RunScenarioService
from semantix_passbudget.interfaces.dto import load_fixture
from semantix_passbudget.ports.persisted_rows import result_rows, rows_hash, rows_view
from tests.integration.postgres_guard import (
    POSTGRES_UNSUPPORTED_FIXTURES,
    postgres_capable_fixtures,
    require_disposable_url,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "src" / "semantix_passbudget" / "fixtures"

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine():  # type: ignore[no-untyped-def]
    url = require_disposable_url()
    created = create_engine(url, hide_parameters=True, future=True)
    with created.connect() as connection:
        major = int(connection.execute(text("SHOW server_version_num")).scalar_one()) // 10_000
        if major < 16:
            pytest.fail(f"PostgreSQL 16+ required, found {major}")
        connection.execute(text("DROP SCHEMA IF EXISTS passbudget CASCADE"))
        # Reset Alembic state as well as the application schema. Otherwise a repeated test run
        # can leave revision "head" in public while all passbudget tables have been removed.
        connection.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
        connection.commit()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    yield created
    created.dispose()


def _compute(name: str):  # type: ignore[no-untyped-def]
    snapshot = load_fixture(FIXTURES / f"{name}.json").to_domain()
    service = RunScenarioService(
        SyntheticContactProvider(),
        InMemoryRunRepository(),
        orbit_provider=OrbitContactProvider(),
    )
    return service.run(snapshot)


@pytest.mark.parametrize("fixture_id", postgres_capable_fixtures())
def test_persistence_round_trip_preserves_rows_and_hashes(engine, fixture_id: str) -> None:  # type: ignore[no-untyped-def]
    run = _compute(fixture_id)
    repository = PostgresRunRepository(engine)
    repository.add(run)
    loaded = repository.get(run.run_id)
    assert loaded is not None
    assert loaded.input_snapshot_hash == run.input_snapshot_hash
    assert loaded.result_content_hash == run.result_content_hash
    assert loaded.run_record_hash == run.run_record_hash
    assert loaded.status == run.status
    assert loaded.stages == run.stages
    assert loaded.persisted_rows is not None
    assert rows_view(loaded.persisted_rows) == rows_view(result_rows(run.result))
    assert rows_hash(loaded.persisted_rows) == rows_hash(result_rows(run.result))


def test_synthetic_run_stores_no_orbit_revision_and_no_elevation(engine) -> None:  # type: ignore[no-untyped-def]
    run = _compute("PB-GOLDEN-CORE-01")
    PostgresRunRepository(engine).add(run)
    with engine.connect() as connection:
        revision = connection.execute(
            text(
                "SELECT contact_source, orbit_revision_id, synthetic_contact_provider_revision "
                "FROM passbudget.scenario_revision WHERE decision_question LIKE 'How many%'"
            )
        ).first()
        assert revision is not None
        assert revision[0] == "SYNTHETIC_INJECTED"
        assert revision[1] is None
        assert revision[2] == "SYN-CONTACT-01-R1"
        elevations = connection.execute(
            text(
                "SELECT count(*) FROM passbudget.geometric_access "
                "WHERE contact_source = 'SYNTHETIC_INJECTED' "
                "AND (maximum_elevation_udeg IS NOT NULL OR maximum_elevation_at IS NOT NULL)"
            )
        ).scalar_one()
        assert elevations == 0


def test_orbit_derived_run_stores_a_typed_orbit_revision(engine) -> None:  # type: ignore[no-untyped-def]
    run = _compute("PB-GOLDEN-ORB-01")
    PostgresRunRepository(engine).add(run)
    with engine.connect() as connection:
        orbit = connection.execute(
            text(
                "SELECT o.orbit_kind, o.earth_radius_m, o.altitude_m, "
                "o.inclination_udeg, o.raan_udeg, o.argument_of_latitude_udeg "
                "FROM passbudget.scenario_revision s "
                "JOIN passbudget.orbit_revision o ON o.revision_id = s.orbit_revision_id "
                "WHERE s.contact_source = 'ORBIT_DERIVED'"
            )
        ).one()
    assert tuple(orbit) == ("VIRTUAL_CIRCULAR", 6_378_137, 700_000, 98_000_000, 90_000_000, 0)


def test_orbit_derived_row_still_requires_a_maximum_elevation(engine) -> None:  # type: ignore[no-untyped-def]
    """The v0.1 contract is unweakened: an ORBIT_DERIVED access row cannot omit the peak."""
    # `engine.begin()` would try to COMMIT a transaction the failed statement already
    # invalidated, and SQLAlchemy raises PendingRollbackError instead of the error under test.
    # Roll back explicitly so the assertion sees the constraint violation itself.
    with engine.connect() as connection:
        with pytest.raises(IntegrityError) as caught:
            connection.execute(
                text(
                    "INSERT INTO passbudget.geometric_access "
                    "(result_id, scenario_station_id, true_aos, true_los, clipped_start, "
                    " clipped_end, contact_source) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), now(),"
                    " now() + interval '1 min', now(), now() + interval '1 min', 'ORBIT_DERIVED')"
                )
            )
        connection.rollback()
    assert "geometric_elevation_source_ck" in str(caught.value)


def test_terminal_run_cannot_be_rewritten(engine) -> None:  # type: ignore[no-untyped-def]
    run = _compute("PB-GOLDEN-OVERLAP-01")
    repository = PostgresRunRepository(engine)
    repository.add(run)
    with pytest.raises(PersistenceError):
        repository.add(run)
    with engine.connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(
                text("UPDATE passbudget.scenario_run SET status = 'FAILED' WHERE id = :id"),
                {"id": run.run_id},
            )
        connection.rollback()


def test_rerunning_the_same_semantic_input_reuses_one_snapshot(engine) -> None:  # type: ignore[no-untyped-def]
    first = _compute("PB-GOLDEN-HORIZON-01")
    second = _compute("PB-GOLDEN-HORIZON-01")
    assert first.input_snapshot_hash == second.input_snapshot_hash
    assert first.run_id != second.run_id
    repository = PostgresRunRepository(engine)
    repository.add(first)
    repository.add(second)
    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM passbudget.input_snapshot WHERE content_sha256 = :digest"),
            {"digest": bytes.fromhex(first.input_snapshot_hash)},
        ).scalar_one()
    assert count == 1


@pytest.mark.parametrize("fixture_id", POSTGRES_UNSUPPORTED_FIXTURES)
def test_an_unsupported_release_trigger_is_refused_not_silently_stored(
    engine, fixture_id: str
) -> None:  # type: ignore[no-untyped-def]
    """`CONFLICT-STORE-01`, asserted rather than assumed.

    `release_trigger = ACKED` is a P0 acceptance requirement (AC-25B) that the accepted v0.1
    enum cannot express. The domain computes it and the SQLite tier stores it; PostgreSQL must
    refuse it loudly. A silent success here would mean the schema had been widened without a
    decision, and a silent skip would hide that the conflict is still open.
    """
    run = _compute(fixture_id)
    repository = PostgresRunRepository(engine)
    with pytest.raises(PersistenceError):
        repository.add(run)
    # The refusal must not leak the connection string or the driver's context.
    try:
        repository.add(run)
    except PersistenceError as caught:
        message = str(caught)
    assert "postgresql" not in message.lower()
    assert "127.0.0.1" not in message
    assert "password" not in message.lower()
