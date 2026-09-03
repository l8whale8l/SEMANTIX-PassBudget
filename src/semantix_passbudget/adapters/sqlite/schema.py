"""SQLite schema management for the default local store.

The migration model is deliberately simpler than Alembic's: SQLite is the *local* tier, a single
file that one process owns, so schema evolution is a linear list of numbered scripts applied in
order and recorded in `schema_version`. Applying them is idempotent — a database already at the
head version is left untouched — so `passbudget` can open an existing file or create a new one
without the operator running a separate command.

`downgrade` is deliberately not supported for SQLite; the rationale is recorded in
`docs/architecture/ADR-0003-persistence-tiers.md`. Recovering an older local file means restoring
a copy of it, which is a file copy rather than a schema operation.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
#: Bundled migration scripts, applied in ascending version order.
_SCRIPTS: tuple[tuple[int, str], ...] = ((1, "schema_v1.sql"),)

#: The DDL has one authoritative home, `db/sqlite/`, and is force-included in the wheel at
#: `semantix_passbudget/_ddl/sqlite/` so `pip install` alone is enough to open a local database.
_PACKAGED_DDL_DIR = Path(__file__).resolve().parents[1].parent / "_ddl" / "sqlite"
_REPOSITORY_DDL_DIR = Path(__file__).resolve().parents[4] / "db" / "sqlite"


def ddl_dir() -> Path:
    """Where the SQLite DDL lives: inside the installed package, else in the source checkout."""
    if (_PACKAGED_DDL_DIR / _SCRIPTS[0][1]).is_file():
        return _PACKAGED_DDL_DIR
    return _REPOSITORY_DDL_DIR


#: Wait rather than fail immediately when another connection holds the write lock.
BUSY_TIMEOUT_MS = 5_000


class SqliteSchemaError(RuntimeError):
    """A local database file could not be brought to the expected schema version."""


@dataclass(frozen=True, slots=True)
class SchemaState:
    version: int
    applied_at_us: int


def _script(name: str) -> str:
    path = ddl_dir() / name
    if not path.is_file():
        raise SqliteSchemaError(
            f"the SQLite schema script {name} is missing from the installation. Reinstall the "
            "package; the DDL ships with it."
        )
    return path.read_text(encoding="utf-8")


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with the pragmas this schema depends on.

    * `foreign_keys` is off by default in SQLite and must be enabled per connection, otherwise
      every `REFERENCES` clause in the schema is decorative.
    * `journal_mode=WAL` lets a reader run while a writer commits, which the API needs.
      It is skipped for in-memory databases, where WAL is not available.
    * `busy_timeout` turns an immediate `database is locked` into a bounded wait.
    """
    target = str(path)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys = ON")
    if target != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def current_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if row is None:
        return 0
    stored = connection.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    return 0 if stored is None else int(stored["version"])


def migrate(connection: sqlite3.Connection) -> SchemaState:
    """Bring a connection to `SCHEMA_VERSION`. Safe to call on every open."""
    version = current_version(connection)
    if version > SCHEMA_VERSION:
        raise SqliteSchemaError(
            f"the local database is at schema version {version} but this build understands "
            f"version {SCHEMA_VERSION}. Upgrade the application rather than downgrading the file."
        )
    applied_at = int((datetime.now(UTC) - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds() * 1e6)
    for target, name in _SCRIPTS:
        if target <= version:
            continue
        # `executescript` commits any open transaction before it runs, so the BEGIN/COMMIT pair
        # has to live inside the script text. SQLite DDL is transactional: a failure part-way
        # rolls the whole step back and leaves `schema_version` untouched.
        record_version = (
            "INSERT INTO schema_version (id, version, applied_at_us) "
            f"VALUES (1, {target:d}, {applied_at:d}) "
            "ON CONFLICT(id) DO UPDATE SET version = excluded.version, "
            "applied_at_us = excluded.applied_at_us;"
        )
        connection.executescript("\n".join(("BEGIN;", _script(name), record_version, "COMMIT;")))
        version = target
    state = connection.execute(
        "SELECT version, applied_at_us FROM schema_version WHERE id = 1"
    ).fetchone()
    if state is None:  # pragma: no cover - only reachable if a script forgets its version row
        raise SqliteSchemaError("schema migration finished without recording a version")
    return SchemaState(version=int(state["version"]), applied_at_us=int(state["applied_at_us"]))


def open_database(path: Path | str) -> sqlite3.Connection:
    """Open and migrate in one step. This is what the composition root calls."""
    connection = connect(path)
    migrate(connection)
    return connection
