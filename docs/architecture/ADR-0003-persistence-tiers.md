# ADR-0003: SQLite is the default local store; PostgreSQL is an optional server tier

- Status: Accepted for P0 (supersedes the persistence clause of ADR-0001)
- Date: 2026-09-03
- Decided by: PM. This ADR records the decision, its consequences and the documents it conflicts
  with; it does not reinterpret them.

## Context

ADR-0001 states: *"PostgreSQL 16+ is the P0 authority because the accepted schema relies on typed
constraints, immutable revisions, deferred integrity checks and deterministic run records. SQLite
may be used only for isolated experiments and is not a supported substitute for authoritative P0
persistence."* `docs/specs/P0_FUNCTIONAL_SPEC.md` §15.3 and the Definition of Done in §16 assume
the same.

Running the product turned that assumption into a cost:

- A new contributor cannot see a result without installing PostgreSQL or Docker.
- The last two verification passes could not run a single live persistence test, because the
  development machine had no PostgreSQL, no Docker and no working WSL. Two acceptance criteria
  (AC-P0-10, AC-P0-20) stayed `PARTIAL` for an environment reason rather than a code reason.
- The product's own contract says the calculation core is framework- and database-independent.
  Requiring a server to *store* a result contradicts nothing in the calculation, only in the
  packaging.

## Decision

Three persistence tiers implement one `RunRepository` port.

| Tier | Used for | Selected by |
|---|---|---|
| `memory` | pure calculation: `passbudget validate`, `run`, `verify-golden`, `compare` | the default for calculation entry points |
| `sqlite` | local persistence, and the default for the API | the default for persistent entry points, or `PASSBUDGET_SQLITE_PATH` |
| `postgresql` | server and multi-user deployment | `PASSBUDGET_DATABASE_URL`, or `PASSBUDGET_PERSISTENCE=postgresql` |

Consequences of the tiering:

1. **PostgreSQL is never implicit.** An unset, empty or whitespace-only `PASSBUDGET_DATABASE_URL`
   resolves to SQLite or memory. There is no fallback that could join a live deployment by
   accident.
2. **The calculation path needs no database at all.** `passbudget run` without `--persist` opens
   no file and creates none.
3. **`pip install` is sufficient.** The SQLite DDL is force-included in the wheel, so a fresh
   install can create a local database with no source checkout, no Docker and no server.
4. **PostgreSQL is kept working, not deprecated.** Its adapter, its Alembic migrations and its
   integration tests remain; they are skipped, never silently passed, when no disposable test
   database is configured.
5. **The domain and application layers still know nothing about any of this.** They see the
   `RunRepository` port. `application/composition.py` is the only module that reads the
   environment, and `tests/unit/test_architecture.py` enforces that.

### Exact-integer representation in SQLite

SQLite's `INTEGER` is signed 64-bit, maximum `9,223,372,036,854,775,807`. The accepted PostgreSQL
schema declares byte and count columns as `numeric(20,0)` (maximum `10^20 - 1`) and metric values
as `numeric(39,0)` (maximum `10^39 - 1`). Both exceed `int64`, the first by roughly an order of
magnitude and the second by twenty.

Storing those as `INTEGER` would truncate or coerce at the top of the domain, and storing them as
`REAL` would violate the exact-arithmetic contract outright. **Exact integers are therefore stored
as canonical decimal `TEXT`**, with a `GLOB` `CHECK` rejecting anything that is not a decimal
string, and converted to Python `int` — arbitrary precision — on the way out. The narrowing is
never silent and never lossy;
`tests/integration/test_sqlite_migration.py::test_a_byte_count_above_int64_survives_the_round_trip`
holds `10^20 - 1` to it.

Timestamps are the opposite case and are stored as `INTEGER` UTC epoch microseconds: the year 9999
is `253402300799999999` µs, four orders of magnitude inside `int64`. The canonical fixed
six-digit `...Z` string is reconstructed on read, so the hash contract of `PB-C14N-JSON-V1` is
untouched.

### The rendered result document

`db/sqlite/schema_v1.sql` has a `run_result_document` table holding the canonical result JSON and
its `content_sha256`. The typed rows remain the relational record of a run; the document is the
versioned immutable execution artifact, which is exactly the role ADR-008 gives
`input_snapshot.canonical_payload` on the input side. It exists so a restarted process can serve
`GET /api/v1/runs/{id}/results` without recomputing, and its hash is checked against
`scenario_run.result_content_hash` on every read.

The accepted PostgreSQL v0.1 schema has no equivalent table and this project does not invent one.
A run fetched from the PostgreSQL tier after a restart therefore returns `501
RESULT_DOCUMENT_NOT_PERSISTED` from `/results`, `/report` and `/comparisons` rather than an empty
object that could be mistaken for a computed result. Closing that gap needs a Data Architect
decision; it is registered as `CONFLICT-STORE-02`.

### SQLite migrations have no downgrade

The SQLite tier applies numbered scripts in order and records the applied version in
`schema_version`. Re-opening a database at the head version is a no-op, so the CLI and the API can
open an existing file or create a new one without a separate command.

Downgrade is deliberately unsupported. A local database is one file owned by one user; the correct
recovery is to restore a copy of that file, which is a file operation rather than a schema
operation. Writing a reverse script would create a second, less-tested path for destroying local
data. Opening a file whose recorded version is *newer* than the build understands raises
`SqliteSchemaError` and refuses to touch it, rather than downgrading it.

The PostgreSQL tier keeps Alembic upgrade *and* downgrade, because a server schema is shared and
an operator needs a defined rollback.

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Keep PostgreSQL as the only persistence | Makes a first run cost a server install, and leaves two acceptance criteria unverifiable on an ordinary machine. This is the situation the PM decision changes. |
| Drop PostgreSQL | Loses deferred constraint checks, triggers and a shared multi-writer story that the accepted schema was designed around. The decision is to demote it, not to remove it. |
| Use SQLAlchemy for the SQLite tier too | The local tier needs no dialect abstraction and no ORM. The standard library's `sqlite3` keeps the default install lighter and the SQL explicit. |
| One shared DDL for both engines | The two engines diverge where it matters — `numeric(20,0)` versus decimal text, native enums versus `TEXT CHECK`, deferred constraint triggers versus none. Sharing one file would hide those differences instead of documenting them. |
| Store the whole result as one JSON blob in SQLite | Forbidden by §12 of the functional specification and by ADR-009. The typed rows are the record; the document sits *beside* them. |

## Consequences

### Positive

- `pip install` then `passbudget verify-golden` works on a bare machine.
- AC-P0-10 and AC-P0-20 become verifiable without a server, and both are now `PASS`.
- Three tiers behind one port make a repository bug visible as a difference between tiers;
  `tests/integration/test_repository_equivalence.py` compares them on every stored fact.

### Negative

- Two schemas to maintain. The SQLite DDL mirrors the PostgreSQL contract by hand, so a change to
  one must be mirrored in the other; the equivalence suite is what catches a divergence.
- SQLite is a single-writer store. It is documented as unsuitable for a concurrent multi-user
  deployment, which is precisely what the PostgreSQL tier is for.
- The PostgreSQL tier cannot serve the rendered result document (`CONFLICT-STORE-02`).

## Conflicts with existing documents

Recorded in full in `docs/specs/SPEC_CONFLICT_REGISTER.md`:

- `CONFLICT-PERSIST-01` — ADR-0001's persistence clause and `P0_FUNCTIONAL_SPEC.md` §15.3/§16.2
  name PostgreSQL as the P0 authority. This ADR supersedes that clause on the PM's decision. The
  original text is not edited; this ADR is the newer decision and says so.
- `CONFLICT-STORE-02` — the PostgreSQL tier has nowhere to store the rendered result document.

## Revisit conditions

Revisit if a deployment needs concurrent writers by default, if the local schema starts diverging
from the PostgreSQL contract faster than the equivalence suite can catch, or if a Data Architect
decision adds a result-document table to the accepted PostgreSQL schema.
