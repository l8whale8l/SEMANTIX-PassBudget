"""Apply the accepted PostgreSQL v0.1 schema without rewriting it."""

from __future__ import annotations

from pathlib import Path

from alembic import context, op

revision = "0001_schema_v0_1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    ddl_path = Path(__file__).resolve().parents[2] / "db" / "postgresql" / "schema_v0_1.sql"
    ddl = ddl_path.read_text(encoding="utf-8")
    body = "\n".join(
        line
        for line in ddl.removeprefix("\ufeff").splitlines()
        if line.strip() not in {"BEGIN;", "COMMIT;"}
    )
    if context.is_offline_mode():
        op.execute(body)
    else:
        # psycopg uses ``pyformat`` paramstyle even when SQLAlchemy executes a
        # driver-level string without parameters.  PostgreSQL PL/pgSQL RAISE
        # format markers therefore have to cross the DBAPI as ``%%`` so the
        # server receives the authoritative single ``%`` from schema_v0_1.sql.
        op.get_bind().exec_driver_sql(body.replace("%", "%%"))


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS passbudget CASCADE")
