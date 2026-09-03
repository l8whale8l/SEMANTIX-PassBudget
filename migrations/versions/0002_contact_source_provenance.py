"""Contact source provenance so synthetic injected contacts need no invented orbit or elevation.

See docs/architecture/ADR-0002-synthetic-contact-provenance.md. The baseline revision
0001_schema_v0_1 is not rewritten; this revision applies an additive delta.
"""

from __future__ import annotations

from pathlib import Path

from alembic import context, op

revision = "0002_contact_source_provenance"
down_revision = "0001_schema_v0_1"
branch_labels = None
depends_on = None

_DDL_DIR = Path(__file__).resolve().parents[2] / "db" / "postgresql"

_SYNTHETIC_ROW_COUNTS = """
SELECT
  (SELECT count(*) FROM passbudget.scenario_revision
     WHERE contact_source = 'SYNTHETIC_INJECTED') AS scenario_revisions,
  (SELECT count(*) FROM passbudget.scenario_station
     WHERE contact_source = 'SYNTHETIC_INJECTED') AS scenario_stations,
  (SELECT count(*) FROM passbudget.geometric_access
     WHERE contact_source = 'SYNTHETIC_INJECTED') AS geometric_accesses
"""


def _statements(name: str) -> str:
    text = (_DDL_DIR / name).read_text(encoding="utf-8").removeprefix("﻿")
    return "\n".join(
        line for line in text.splitlines() if line.strip() not in {"BEGIN;", "COMMIT;"}
    )


def _run(name: str) -> None:
    body = _statements(name)
    if context.is_offline_mode():
        op.execute(body)
    else:
        # Keep raw migration files driver-independent. psycopg's pyformat
        # parser requires literal percent signs to be doubled at this boundary.
        op.get_bind().exec_driver_sql(body.replace("%", "%%"))


def upgrade() -> None:
    _run("schema_v0_2_contact_source.sql")


def downgrade() -> None:
    if not context.is_offline_mode():
        row = op.get_bind().exec_driver_sql(_SYNTHETIC_ROW_COUNTS).one()
        if any(row):
            raise RuntimeError(
                "downgrade would require inventing an orbit revision and a maximum elevation for "
                f"{row.scenario_revisions} scenario_revision, {row.scenario_stations} "
                f"scenario_station and {row.geometric_accesses} geometric_access rows recorded as "
                "SYNTHETIC_INJECTED. Schema v0.1 cannot represent them. Remove or migrate those "
                "rows deliberately first; this downgrade is intended for disposable databases."
            )
    _run("schema_v0_2_contact_source_down.sql")
