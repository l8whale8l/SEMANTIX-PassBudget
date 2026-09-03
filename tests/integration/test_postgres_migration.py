from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from tests.integration.postgres_guard import require_disposable_url

ROOT = Path(__file__).resolve().parents[2]


def test_baseline_preserves_accepted_ddl() -> None:
    ddl = (ROOT / "db" / "postgresql" / "schema_v0_1.sql").read_text(encoding="utf-8")
    migration = (ROOT / "migrations" / "versions" / "0001_schema_v0_1_baseline.py").read_text(
        encoding="utf-8"
    )
    assert ddl.count("CREATE TABLE ") == 30
    assert 'revision = "0001_schema_v0_1"' in migration
    assert '"db" / "postgresql" / "schema_v0_1.sql"' in migration
    assert 'body.replace("%", "%%")' in migration


def test_delta_is_additive_and_has_a_single_head() -> None:
    script = ScriptDirectory(str(ROOT / "migrations"))
    assert list(script.get_heads()) == ["0002_contact_source_provenance"]
    delta = (ROOT / "db" / "postgresql" / "schema_v0_2_contact_source.sql").read_text(
        encoding="utf-8"
    )
    assert "DROP TABLE" not in delta.upper()
    assert "DROP COLUMN" not in delta.upper()
    # The one dropped constraint is replaced in the same file by its conditional form.
    assert delta.count("DROP CONSTRAINT") == 1
    assert "geometric_elevation_source_ck" in delta
    assert delta.count("SET search_path = pg_catalog, passbudget;") == 17
    assert (
        "ALTER FUNCTION passbudget.guard_result_child_insert() "
        "SET search_path = pg_catalog, passbudget;"
    ) in delta
    assert delta.isascii(), "delta DDL stays ASCII so offline --sql output is portable"


@pytest.mark.postgres
def test_postgresql_16_clean_upgrade_and_downgrade() -> None:
    database_url = require_disposable_url()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    engine = create_engine(database_url, hide_parameters=True)
    with engine.connect() as connection:
        major = int(connection.execute(text("SHOW server_version_num")).scalar_one()) // 10_000
        if major < 16:
            pytest.fail(f"PostgreSQL 16+ required, found {major}")
        connection.execute(text("DROP SCHEMA IF EXISTS passbudget CASCADE"))
        # The disposable test database may retain Alembic's public version table from a
        # previous run. Reset it together with the owned schema so upgrade() cannot mistake
        # a schema-less database for an already-migrated one.
        connection.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
        connection.commit()

    command.upgrade(config, "0001_schema_v0_1")
    assert len(inspect(engine).get_table_names(schema="passbudget")) == 30

    command.upgrade(config, "head")
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("geometric_access", schema="passbudget")
    }
    assert "contact_source" in columns
    with engine.connect() as connection:
        nullable = connection.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'passbudget' AND table_name = 'scenario_revision' "
                "AND column_name = 'orbit_revision_id'"
            )
        ).scalar_one()
    assert nullable == "YES"

    command.downgrade(config, "0001_schema_v0_1")
    with engine.connect() as connection:
        restored = connection.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'passbudget' AND table_name = 'scenario_revision' "
                "AND column_name = 'orbit_revision_id'"
            )
        ).scalar_one()
    assert restored == "NO"
    assert len(inspect(engine).get_table_names(schema="passbudget")) == 30

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names(schema="passbudget") == []
    engine.dispose()
