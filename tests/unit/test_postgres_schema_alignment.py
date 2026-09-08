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
from sqlalchemy import Enum as SqlAlchemyEnum
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
CREATE_TYPE_BODY = re.compile(r"CREATE TYPE (\w+) AS ENUM\s*\((.*?)\);", re.DOTALL)


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


def _declared_enum_labels() -> dict[str, tuple[str, ...]]:
    labels: dict[str, tuple[str, ...]] = {}
    for name, body in CREATE_TYPE_BODY.findall(BASE_DDL) + CREATE_TYPE_BODY.findall(DELTA_DDL):
        labels[name] = tuple(re.findall(r"'([^']+)'", body))
    return labels


def _enum_types() -> list[SqlAlchemyEnum]:
    found: list[SqlAlchemyEnum] = []
    for table in tables.metadata.tables.values():
        for column in table.columns:
            for candidate in (column.type, getattr(column.type, "item_type", None)):
                if isinstance(candidate, SqlAlchemyEnum):
                    found.append(candidate)
    return found


def test_every_enum_column_reads_its_stored_label_back_unchanged() -> None:
    """A labelless enum reference stores rows happily and then fails every single read.

    `sqlalchemy.Enum` is asymmetric when it carries no labels: `_db_value_for_elem` lets an
    unrecognised string through on the way in, while `_object_value_for_elem` raises
    `LookupError: ... Possible values: None` on the way out. A write-only check therefore
    cannot catch it, and neither can any suite that runs without PostgreSQL -- which is how it
    reached CI. This asserts the round trip in pure Python, for every enum the adapter names.
    """
    dialect = postgresql.dialect()
    declared = _declared_enum_labels()
    enum_types = _enum_types()
    assert enum_types, "the adapter maps no enum columns; this test would prove nothing"
    for enum_type in enum_types:
        assert enum_type.name in declared, f"{enum_type.name} is not declared in the DDL"
        processor = enum_type.result_processor(dialect, None)
        for label in declared[enum_type.name]:
            read_back = label if processor is None else processor(label)
            assert read_back == label, (
                f"{enum_type.name} does not survive a read: {label!r} came back as {read_back!r}"
            )


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
