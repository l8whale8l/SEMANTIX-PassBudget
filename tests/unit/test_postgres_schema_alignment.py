"""Static alignment between the SQLAlchemy tables and the accepted DDL.

Without a live server this is what can still be proven: every table and column the adapter names
exists in `db/postgresql/schema_v0_1.sql` plus the v0.2 delta, every enum type it references
is declared, and every statement it builds compiles against the PostgreSQL dialect. A typo in
a column name would otherwise only surface in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import insert, select
from sqlalchemy.dialects import postgresql

from semantix_passbudget.adapters.postgres import schema as tables

ROOT = Path(__file__).resolve().parents[2]
BASE_DDL = (ROOT / "db" / "postgresql" / "schema_v0_1.sql").read_text(encoding="utf-8")
DELTA_DDL = (ROOT / "db" / "postgresql" / "schema_v0_2_contact_source.sql").read_text(
    encoding="utf-8"
)

CREATE_TABLE = re.compile(r"CREATE TABLE (\w+) \((.*?)\n\);", re.DOTALL)
ADD_COLUMN = re.compile(r"ALTER TABLE (\w+)\s+ADD COLUMN (\w+)", re.MULTILINE)
ADD_COLUMN_EXTRA = re.compile(r"^\s+ADD COLUMN (\w+)", re.MULTILINE)
CREATE_TYPE = re.compile(r"CREATE TYPE (\w+) AS ENUM")


def _declared_columns() -> dict[str, set[str]]:
    declared: dict[str, set[str]] = {}
    for name, body in CREATE_TABLE.findall(BASE_DDL):
        columns: set[str] = set()
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("CONSTRAINT", "FOREIGN KEY", "UNIQUE", "--")):
                continue
            columns.add(stripped.split()[0].rstrip(","))
        declared[name] = columns
    # The delta adds columns through ALTER TABLE, including multi-column statements.
    for statement in DELTA_DDL.split(";"):
        match = re.search(r"ALTER TABLE (\w+)", statement)
        if match is None:
            continue
        table = match.group(1)
        for column in ADD_COLUMN_EXTRA.findall(statement):
            declared.setdefault(table, set()).add(column)
    return declared


DECLARED = _declared_columns()
DECLARED_TYPES = set(CREATE_TYPE.findall(BASE_DDL)) | set(CREATE_TYPE.findall(DELTA_DDL))


@pytest.mark.parametrize("table", sorted(tables.metadata.tables.values(), key=lambda t: t.name))
def test_every_mapped_column_exists_in_the_accepted_ddl(table: object) -> None:
    name = table.name  # type: ignore[attr-defined]
    assert name in DECLARED, f"{name} is not a table in the accepted DDL"
    mapped = {column.name for column in table.columns}  # type: ignore[attr-defined]
    unknown = mapped - DECLARED[name]
    assert not unknown, f"{name} maps columns that do not exist: {sorted(unknown)}"


def test_every_referenced_enum_type_is_declared() -> None:
    referenced = {
        column.type.name
        for table in tables.metadata.tables.values()
        for column in table.columns
        if getattr(column.type, "name", None) and hasattr(column.type, "enums")
    }
    referenced |= {
        column.type.item_type.name
        for table in tables.metadata.tables.values()
        for column in table.columns
        if hasattr(column.type, "item_type") and hasattr(column.type.item_type, "enums")
    }
    unknown = referenced - DECLARED_TYPES
    assert not unknown, f"undeclared enum types: {sorted(unknown)}"


def test_statements_compile_against_the_postgresql_dialect() -> None:
    dialect = postgresql.dialect()
    for table in tables.metadata.tables.values():
        compiled = str(select(table).compile(dialect=dialect))
        assert f'passbudget."{table.name}"' in compiled or f"passbudget.{table.name}" in compiled
        values = {column.name: None for column in table.columns}
        assert str(insert(table).values(**values).compile(dialect=dialect))


def test_no_ddl_is_emitted_from_the_adapter() -> None:
    """The adapter never creates or alters schema; Alembic owns every migration."""
    source = (
        ROOT / "src" / "semantix_passbudget" / "adapters" / "postgres" / "schema.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("create_all", "drop_all", "CreateTable", "create_type=True"):
        assert forbidden not in source
