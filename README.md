# SEMANTIX PassBudget

SEMANTIX PassBudget is an early mission-design decision-support tool that combines satellite orbit assumptions, ground-station configurations, modeled communication capacity, and onboard data products to compare contact opportunities, logical downlink budgets, and payload priorities.

It does **not** guarantee ground-station availability, communication success, actual delivery, or operational approval.

## Project status

The executable P0 core covers synthetic contact and capacity arithmetic, overlap resolution, a
horizon-aware queue objective evaluated over the whole analysis window, an event-ordered
queue/storage ledger, bundle and dependency contracts, named gap metrics, reporting, run
comparison, and three interchangeable persistence tiers. The queue objective is global and is
searched exactly by default; an instance too dense in genuine conflicts is refused by name rather
than answered with a silent approximation, and a declared approximate mode exists for those
instances (see **Execution strategy**). The CLI and the HTTP API call the same application
service. These are synthetic concept-validation results, not orbit or radio-performance
predictions.

The orbit evidence that blocked release is now **complete**. A frozen public TLE and a synthetic
circular orbit are each computed by the product engine and independently by NASA GMAT, and the two
agree far inside tolerances that were fixed before anything was computed — worst AOS error 17 ms
against a 1.000 s ceiling, over 58 passes, with zero ceiling breaches. See
[the orbit evidence](evidence/orbit/README.md) and
[the release gate audit](docs/specs/ORBIT_RELEASE_GATE.md).

The orbit evidence gate is **PASS**. The release status is `P0_RELEASE_BLOCKED_ORBIT_INTEGRATION`:
the cross-tool agreement is proven, and this change set connects the verified orbit engine to the
product. `ORBIT_DERIVED` now takes an orbit assumption (a user TLE or literal two-body elements)
plus WGS-84 station coordinates and a minimum elevation, generates the day's contact windows, and
feeds them into the existing assumed-throughput capacity and model-output prioritisation over both
the API and the CLI (see `PB-GOLDEN-ORB-01`). The remaining gate is CI: the release is unblocked
only once the required GitHub Actions pass on the pushed commit. Every orbit result is an
assumption-based estimate over synthetic inputs, never a KMU-ET02 performance figure.

Specification conflicts and how each was resolved are in
[the conflict register](docs/specs/SPEC_CONFLICT_REGISTER.md), and the acceptance-criteria status is
in [the P0 acceptance matrix](docs/specs/P0_ACCEPTANCE_MATRIX.md), with the wider Definition of
Done tracked in [the DoD status](docs/specs/P0_DEFINITION_OF_DONE.md).

## Architecture direction

- Python, CPU-first implementation
- Framework-independent deterministic core engine
- The same core is called by CLI, API, tests, and future UI
- Three persistence tiers behind one repository port: in-memory, SQLite (default local),
  PostgreSQL (optional server)
- HTTP API as an outer adapter, not the owner of calculation rules
- Container-based deployment without CUDA or H100 dependency
- Optional native optimization only after profiling proves a bottleneck

```text
CLI / HTTP API
      |
Application services (run, catalog lifecycle, comparison) + composition root
      |
Deterministic domain core
  | Capacity | Scheduler | Horizon objective | Queue/Storage ledger | Canonicalization |
      |
Ports: run repository, catalog repository, contact provider, persisted-row contract
      |
in-memory  |  SQLite (default local)  |  PostgreSQL (optional server)  |  synthetic contacts
```

The domain and application layers never see SQLAlchemy, `sqlite3` or a database URL.
`application/composition.py` is the only module that reads the environment, and
`tests/unit/test_architecture.py` enforces both rules.

See [ADR-0001](docs/architecture/ADR-0001-runtime-and-portability.md) for the runtime rationale,
[ADR-0002](docs/architecture/ADR-0002-synthetic-contact-provenance.md) for how synthetic injected
contacts are stored without inventing an orbit revision or a maximum elevation, and
[ADR-0003](docs/architecture/ADR-0003-persistence-tiers.md) for why SQLite is the default local
store and PostgreSQL an optional tier.

## Install and first run

Python 3.12 is required. Nothing else is: no PostgreSQL, no Docker, no network service.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

On Linux or macOS use `source .venv/bin/activate && pip install -e ".[dev]"`. A plain
`pip install .` is enough to use the tool; the `[dev]` extra only adds the test and lint tools.

Every calculation command runs entirely in memory — no database file is created or opened:

```bash
passbudget verify-golden
```

```bash
passbudget validate PB-GOLDEN-CORE-01
```

```bash
passbudget run PB-GOLDEN-CORE-01 --output result.json
```

```bash
passbudget compare result.json queue-result.json
```

## Persistence tiers

| Tier | What it is for | How it is selected |
|---|---|---|
| `memory` | Pure calculation. Nothing is written anywhere. | The default for `validate`, `run`, `verify-golden` and `compare`. |
| `sqlite` | Local persistence and the API's default store. One file, no server. | The default for the API and for `run --persist`; `PASSBUDGET_SQLITE_PATH` overrides the location. |
| `postgresql` | Shared, multi-user or server deployment. | Only when `PASSBUDGET_DATABASE_URL` is set, or `PASSBUDGET_PERSISTENCE=postgresql`. |

Precedence, highest first: `PASSBUDGET_PERSISTENCE` → `PASSBUDGET_DATABASE_URL` →
`PASSBUDGET_SQLITE_PATH` → the caller's default. **PostgreSQL is never selected implicitly.** An
unset or empty `PASSBUDGET_DATABASE_URL` resolves to SQLite or memory, so no command can join a
running deployment by accident.

| Variable | Meaning |
|---|---|
| `PASSBUDGET_PERSISTENCE` | Force a tier: `memory`, `sqlite` or `postgresql`. |
| `PASSBUDGET_DATABASE_URL` | PostgreSQL URL. Setting it is the only way to reach the server tier. |
| `PASSBUDGET_SQLITE_PATH` | Path to the local database file. |
| `PASSBUDGET_DATA_DIR` | Base directory for the default local database. |
| `PASSBUDGET_TEST_DATABASE_URL` | Disposable PostgreSQL database for the integration tests only. |

To store a run locally and read it back:

```bash
passbudget run PB-GOLDEN-QUEUE-01 --output queue-result.json --persist
```

```bash
passbudget where
```

```bash
passbudget show <run-id>
```

### Where the local database lives

`passbudget where` prints the resolved tier and the exact file path. By default it is in the
per-user application data directory, never in the repository and never in the working directory:

- Windows: `%LOCALAPPDATA%\SEMANTIX\PassBudget\passbudget.sqlite3`
- Linux and macOS: `$XDG_DATA_HOME/semantix-passbudget/passbudget.sqlite3`, or
  `~/.local/share/semantix-passbudget/passbudget.sqlite3`

The schema is created and upgraded automatically when the file is opened; there is no separate
migration command for the local tier. Re-opening a database that is already current does nothing.

**Back up** by copying the file while no process is writing (WAL mode also creates
`passbudget.sqlite3-wal` and `-shm` beside it; copy all three, or copy after a clean shutdown).
**Reset** by deleting the file — the next command recreates it empty. `.gitignore` already
excludes the database and its journal files.

**SQLite is a single-writer store.** It suits one operator, one CLI, one API process and CI. It is
not for a shared multi-user deployment with concurrent writers; that is what the PostgreSQL tier
is for. Local schema migrations are forward-only by design: recovery means restoring a copy of the
file. The rationale is in [ADR-0003](docs/architecture/ADR-0003-persistence-tiers.md).

### What works without PostgreSQL or Docker

Everything except the PostgreSQL-specific cases: the whole calculation core, all five golden
fixtures, the complete HTTP API including the lifecycle endpoints, local persistence and restart
survival, and the whole default test suite. Only `pytest -m postgres` and `alembic upgrade` against
a server need PostgreSQL, and they are skipped — never reported as passing — when it is absent.

## Public fixtures

All five fixtures live in `src/semantix_passbudget/fixtures/` and are explicitly synthetic. None of
them contains a KMU-ET02 specification, a real TLE, a station coordinate, or a credential.

| Fixture | Mode | What it pins down |
|---|---|---|
| `PB-GOLDEN-CORE-01` | `NETWORK_ONLY` | A/B/C contact counts, exact rate integration, 560,000,000 B candidate and scheduled capacity |
| `PB-GOLDEN-QUEUE-01` | `QUEUE_AWARE` | First-session allocation, modeled completion times, 85,000,000 B backlog after A1, bundle actionability |
| `PB-GOLDEN-OVERLAP-01` | `NETWORK_ONLY` | 440,000,000 B candidate vs 400,000,000 B scheduled unique, suppressed candidate and reason |
| `PB-GOLDEN-HORIZON-01` | `QUEUE_AWARE` | AC-32: a smaller feasible opportunity beats a larger one that misses a MANDATORY deadline |
| `PB-GOLDEN-ACK-01` | `QUEUE_AWARE` | AC-25B object reclaim on `TEST_SYNTHETIC` acknowledgements; an incomplete object holds its footprint |

`PB-GOLDEN-CORE-01` keeps the kickoff-required `NETWORK_ONLY` contract while `PB-GOLDEN-QUEUE-01`
carries the `QUEUE_AWARE` oracle from the golden design document; both use identical contact and
capacity inputs. See `CONFLICT-FIX-01` in the conflict register.

## Execution strategy

The `QUEUE_AWARE` objective is global: conflict components are coupled through the payload queue,
so they cannot be decided independently, and a jointly optimal selection is NP-hard. One algorithm
cannot be both always optimal and always affordable, so the scenario declares which it wants.

| | `EXACT_GLOBAL` (default) | `BOUNDED_APPROXIMATE` |
|---|---|---|
| Guarantees | the global optimum of the specified objective | feasible and deterministic, **and nothing else** |
| How | decompose into conflict components, then score every combination of the branching components' alternatives with one whole-horizon rollout each | three fixed deterministic polynomial interval schedules, each producing a complete selection, scored by the same objective |
| Candidate generation | full maximal-set enumeration (exponential in one component's overlap density) | no component decomposition, no maximal-set enumeration |
| Cost | combinations × instance size | three schedules plus at most three rollouts, whatever the overlap density |
| Budgets | `MAXIMAL_SET_BUDGET`, `GLOBAL_COMBINATION_BUDGET`, `EXACT_WORK_BUDGET` | none — those three and their errors do not apply on this path |
| `optimization_status` | `EXACT` | `APPROXIMATE` |
| `globally_optimal` | `true` | `false` |

The two modes do not share a candidate generator, and the strategy is read before either one
runs. That is a correctness requirement rather than a tidiness one: a single densely connected
component can hold more maximal sets than the exact budget allows while being perfectly ordinary
to schedule greedily, so a shared decomposition would make the approximation refuse exactly the
instances it exists to answer.

**Nothing switches modes on your behalf.** An exact search that exceeds one of its three budgets
fails with a named error; it does not quietly return an approximation. Getting an approximate answer requires asking for one, and the field
belongs to the *scenario*, not to the request — a run names an immutable input and does not
reach in and change it:

```json
{
  "snapshot": {
    "schema_version": "passbudget-input-0.2",
    "fixture_id": "PB-GOLDEN-QUEUE-01",
    "analysis_mode": "QUEUE_AWARE",
    "execution_strategy": "BOUNDED_APPROXIMATE",
    "...": "the rest of the scenario"
  }
}
```

A request-level `execution_strategy` is refused: the packaged fixtures are `EXACT_GLOBAL`
scenarios, and running one approximately means running a different scenario, which is exactly
what the differing input hash records.

The strategy is a semantic input, not a tuning knob. It appears in the canonical input snapshot,
the result, the provenance, the engine manifest and every hash — two runs that differ only in
strategy are two different questions, not two answers to one. Every result carries an
`optimization` block, an approximate result carries a `NOT_GLOBALLY_OPTIMAL` warning, and
comparing results of different grades produces an `OPTIMIZATION_GRADE_MISMATCH` warning so a
number from one mode is not read as a number from the other.

`optimality_gap` is always `null` today. A bound on the scheduled-byte term alone is cheap and
exact, but that is the fifth term of a lexicographic objective: a selection can be byte-optimal
and still miss a MANDATORY deadline the optimum meets, so publishing it under that name would
claim more than the number supports.

`NETWORK_ONLY` is solved exactly by the maximum-capacity dynamic program, so the choice does not
apply there and declaring `BOUNDED_APPROXIMATE` for it is refused.

See `P0_FUNCTIONAL_SPEC.md` §6.5.1 and `CONFLICT-QUEUE-02` in the conflict register.

## Input ceilings

`P0_FUNCTIONAL_SPEC.md` §15.4 requires bounds on input size so a public deployment cannot be
driven into resource exhaustion. Every ceiling lives in one module,
`src/semantix_passbudget/domain/limits.py`, and none of them reads the environment.

| Ceiling | Value |
|---|---|
| Analysis window | 31 days |
| Stations | 200 |
| Contacts | 20,000 |
| Payloads | 10,000 |
| Payload dependencies | 20,000 |
| Rate segments per station | 512 |
| Time reserves per station | 512 |
| Synthetic delivery events | 10,000 |
| HTTP request body | 8 MiB |
| Profile revision payload | 256 KiB |

The request-body ceiling is enforced on **received** bytes as well as on the declared
`Content-Length`, and it stops mid-stream rather than after assembling the body: a chunked request
declares no length at all, and one that declares a length is under no obligation to honour it.

The scenario ceilings are applied in `ScenarioSnapshot.validate()`, not in a DTO: HTTP, the CLI
and a direct domain caller all reach `validate()`, and only some of them reach a DTO. An input
over a ceiling is refused whole with `INPUT_LIMIT_EXCEEDED` and a 4xx status; it is never
truncated, and it never becomes a run. That is deliberately different from a branch-local
calculation failure, where the run exists and its successful branches stay readable. The error
names the limit and the maximum, never the input.

Every ceiling admits the specification's reference analysis — one spacecraft, 20 ground stations,
a 7-day window, 10,000 payloads — and the payload ceiling *is* that reference size, so 10,000 is
accepted and 10,001 is refused.

## HTTP API

```text
uvicorn semantix_passbudget.interfaces.api.app:app --host 127.0.0.1 --port 8000
```

Over HTTP, `fixture` names a public fixture identifier and nothing else. The CLI may still be
given a path — it runs as you, on your machine, against your files — but the API never opens a
file named by a request, and a rejection does not repeat the requested value back.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Process status; no secret or database detail |
| GET | `/api/v1/presets` | Public preset profiles by kind and preset scenarios |
| POST | `/api/v1/profiles` | Create a profile head |
| GET | `/api/v1/profiles/{profile_id}` | Head and revision list |
| POST | `/api/v1/profiles/{profile_id}/revisions` | New draft revision |
| POST | `/api/v1/profile-revisions/{revision_id}/publish` | Publish an immutable revision |
| POST | `/api/v1/scenarios` | Scenario head plus first draft |
| GET | `/api/v1/scenarios/{scenario_id}` | Head, revisions, recent runs |
| POST | `/api/v1/scenarios/{scenario_id}/revisions` | New draft, optionally based on a revision |
| POST | `/api/v1/scenario-revisions/{revision_id}/publish` | Publish after validation |
| POST | `/api/v1/scenario-revisions/{revision_id}/clone` | Independent variant scenario |
| POST | `/api/v1/scenario-revisions/{revision_id}/snapshots` | Immutable executable snapshot, or the blocked branches |
| POST | `/api/v1/runs` | Run from `snapshot_id`, a packaged `fixture`, or an inline `snapshot` |
| GET | `/api/v1/runs/{run_id}` | Run and per-stage status |
| GET | `/api/v1/runs/{run_id}/results` | Typed results and trace |
| GET | `/api/v1/runs/{run_id}/report` | Human-readable summary |
| POST | `/api/v1/comparisons` | Compatible-metric delta between two terminal runs |

Published revisions and terminal runs are immutable: a change makes a new revision, and a rerun
makes a new run. Errors use the specification's structured envelope and never contain a stack
trace, a SQL statement, a database URL, a credential, or a host path.

`GET /health` reports the tier name only (`memory`, `sqlite`, `postgresql`) — never a path, a URL,
a host or a credential.

The API's default store is SQLite, so a run survives a restart with identical input, result and
run hashes. Set `PASSBUDGET_DATABASE_URL` to move it to PostgreSQL. The catalog is in-memory in
this slice and is seeded from the packaged public fixtures at startup.

On the PostgreSQL tier only, `GET /runs/{id}/results`, `/report` and `POST /comparisons` return
`501 RESULT_DOCUMENT_NOT_PERSISTED` for a run fetched after a restart: the accepted v0.1 schema has
nowhere to store the rendered result document, and this project does not invent a table for it. The
gap is registered as `CONFLICT-STORE-02`.

## Orbit verification

The orbit path is verified against an independent implementation, never against itself.

| Role | Tool | Ships? |
|---|---|---|
| Product engine | `adapters/orbit` on [python-sgp4](https://pypi.org/project/sgp4/) 2.27 (MIT) | Yes — a core dependency (pure Python, no data files, no network) now that ORBIT_DERIVED is live |
| Independent oracle | NASA GMAT R2026a (Apache-2.0) | **No.** Offline only; it contributes committed text files. |

Every definition, window, mask and tolerance is fixed in
[the verification contract](docs/specs/ORBIT_VERIFICATION_CONTRACT.md), which was written before any
orbit code existed so that no tolerance could be chosen after seeing a number. The expected tables
are generated from preserved raw GMAT output by a committed converter, so no expected value is a
hand-copied literal.

This is what a second implementation is for: the first `EVD-ORB-02` run failed with 22.3 s AOS
errors, and the cause was a real defect — an IAU-76 precession rotation applied about the wrong
axis, worth 18.29 km of Earth-fixed position. It produced entirely plausible output and no amount
of self-consistency testing would have found it.

The cross-tool tests run in the ordinary suite and need neither GMAT nor the network. The fully
synthetic `EVD-ORB-02` fixture is committed and is the public cross-tool gate. `EVD-ORB-01` is
derived from a CelesTrak-redistributed TLE whose public-redistribution terms are unresolved
(`Q-ORB-LICENSE-01`), so its inputs and oracle artifacts are kept local only; its cases run and
pass where that evidence is present and are skipped — never counted as a pass — where it is
deliberately absent, as in public CI:

```bash
pytest tests/integration/test_orbit_cross_tool.py
```

These are implementation-agreement results on a defined problem, **not** real-world orbital
accuracy and **not** KMU-ET02 performance: the station coordinates are synthetic, and UT1-UTC and
polar motion are forced to zero in both tools. The limitations are listed in
[the evidence README](evidence/orbit/README.md).

## Quality checks

```text
ruff check .
ruff format --check .
mypy src
pytest
passbudget verify-golden
python scripts/secret_scan.py
alembic heads
alembic upgrade head --sql
```

The default suite needs no server. The PostgreSQL cases are marked and run only when a
disposable PostgreSQL 16+ URL is supplied:

```bash
PASSBUDGET_TEST_DATABASE_URL=postgresql+psycopg://passbudget_test:...@127.0.0.1:5432/passbudget_test pytest -m postgres
```

Those tests drop the `passbudget` schema and the Alembic version table, so a guard
(`tests/integration/postgres_guard.py`) refuses any URL that does not look disposable: the host
must be loopback or a known container/CI service name, and the database name must contain `test`,
`ci`, `tmp` or `scratch`. Setting the *runtime* variable `PASSBUDGET_DATABASE_URL` is refused
outright. The refusal names the rule, never the URL.

A local run without PostgreSQL skips those cases; a skip is not evidence and is never reported as
a pass.

## Continuous integration

`.github/workflows/backend.yml` runs on every push and pull request and needs **no database
service at all**. It has four jobs:

| Job | What it proves |
|---|---|
| `verify` | lint, formatting, types, the full 366-test suite including the cross-tool orbit evidence, `verify-golden`, `where`, the secret scan |
| `clean-install` | a wheel installs and runs the golden verification on a machine with no source tree |
| `docker` | the image builds, its CLI works, and a run computed through the API is still readable after the container restarts |
| `audit` | no known advisory affects the dependency set |

`audit` is deliberately its own job: a newly published advisory says something about the
dependency set, not about the code, and the two signals should stay separable in the Actions tab.

`.github/workflows/postgresql.yml` holds everything that needs a live PostgreSQL 16: the offline
migration SQL, `pytest -m postgres`, and the three-tier equivalence suite. It is triggered
manually from the Actions tab, and automatically on `main` when the PostgreSQL adapter, its DDL or
its migrations change. It does not gate ordinary pushes, because PostgreSQL is an optional tier.
If that workflow has not run for a change, the PostgreSQL tier is unverified for it.

## PostgreSQL: the optional server tier

PostgreSQL is not required to install, run or test PassBudget. Use it for a shared or multi-user
deployment, where SQLite's single-writer model is not enough.

`db/postgresql/schema_v0_1.sql` remains the accepted, unchanged physical DDL, applied by Alembic revision
`0001_schema_v0_1`. Revision `0002_contact_source_provenance` applies the additive delta in
`db/postgresql/schema_v0_2_contact_source.sql`, which lets a synthetic injected contact be stored without an
invented orbit revision or maximum elevation while keeping the full v0.1 contract for orbit-derived
contacts. Only run migrations against a new or disposable database:

```text
docker compose up -d postgres
set PASSBUDGET_DATABASE_URL=postgresql+psycopg://passbudget_local:local_development_only@127.0.0.1:5432/passbudget
alembic upgrade head
```

On PowerShell use `$env:PASSBUDGET_DATABASE_URL=...`; on POSIX shells use `export`. The `0002`
downgrade restores the v0.1 contract exactly and refuses to run while any `SYNTHETIC_INJECTED` row
exists, because schema v0.1 cannot represent those rows and this project does not invent values to
satisfy a `NOT NULL`. The `0001` downgrade drops the `passbudget` schema and is for disposable
development databases only. Production credentials must be injected by the deployment environment,
and migration and runtime roles must be separated before deployment.

## Reading a result

- `candidate_capacity_sum_bytes` is the sum before TX conflicts are resolved.
- `scheduled_unique_capacity_bytes` is the primary KPI: what one TX resource is planned to use.
- `suppressed_capacity_bytes` is candidate capacity dropped by conflict resolution.
- `stranded_capacity_bytes` is selected-session capacity that no payload could use.
- `modeled_tx_complete_at` is a *planned* transmission completion, never a ground reception.
- `NOT_APPLICABLE` never means zero and never means unlimited.
- `CONCEPT_ONLY` means the result depends on a synthetic or PROXY assumption.

## Containers

The multi-stage image is CPU-only. `compose.yaml` supplies a local PostgreSQL 16 service and the API
with fake local-development credentials. It does not mount or bake `.env`, SSH material, or private
data into the image.

## Implementation documents

- [P0 functional specification](docs/specs/P0_FUNCTIONAL_SPEC.md)
- [P0 acceptance matrix](docs/specs/P0_ACCEPTANCE_MATRIX.md)
- [P0 Definition of Done status](docs/specs/P0_DEFINITION_OF_DONE.md)
- [Specification conflict register](docs/specs/SPEC_CONFLICT_REGISTER.md)
- [Orbit release gate audit](docs/specs/ORBIT_RELEASE_GATE.md)
- [Orbit verification contract](docs/specs/ORBIT_VERIFICATION_CONTRACT.md)
- [Orbit evidence: EVD-ORB-01 and EVD-ORB-02](evidence/orbit/README.md)
- [ADR-0004: orbit engine, independent oracle, and the JVM question](docs/architecture/ADR-0004-orbit-engine-and-oracle.md)
- [Database schema](docs/database/database_schema_v0.1.md)
- [Schema decisions](docs/database/schema_decisions.md)
- [PostgreSQL 16+ DDL](db/postgresql/schema_v0_1.sql) and [the v0.2 delta](db/postgresql/schema_v0_2_contact_source.sql)
- [Local SQLite schema](db/sqlite/schema_v1.sql)
- [ADR-0003: persistence tiers](docs/architecture/ADR-0003-persistence-tiers.md)
- [Backend kickoff prompt](docs/prompts/BACKEND_KICKOFF_PROMPT.md)

## Public-repository safety

- Real secrets, server addresses, SSH material, private mission data, database dumps, logs, uploads, and exports must not be committed.
- Public fixtures must be synthetic or have an explicitly recorded public source and compatible license.
- Runtime configuration is injected through environment variables or a deployment secret manager.
- The application must remain usable on an ordinary CPU host; an H100 server is one deployment target, not a requirement.

## License

Licensed under the [MIT License](LICENSE).
