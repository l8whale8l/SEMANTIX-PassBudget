# ADR-0001: Python CPU-first backend with replaceable compute adapters

- Status: Accepted for P0
- Date: 2026-09-03

## Context

P0 evaluates one satellite per scenario, multiple ground stations, bounded analysis windows, deterministic access events, exact logical-capacity accounting, interval conflicts, and payload queue/storage policies. The product must run on the team's H100 server and on ordinary third-party machines without GPU hardware.

The core requirement is reproducibility across CLI, API, tests, and UI. Deployment convenience and contributor accessibility are more important than maximizing raw throughput before a measured bottleneck exists.

## Decision

Use Python for the P0 backend and calculation core. The default runtime is CPU-only and has no CUDA dependency.

Use a modular monolith with inward dependencies:

```text
interfaces: CLI, HTTP
        ↓
application: use cases, transactions, validation orchestration
        ↓
domain core: orbit contracts, access, capacity, scheduling, queue/storage
        ↓
ports: orbit provider, repositories, artifact storage, clock
        ↓
adapters: SGP4 library, PostgreSQL, filesystem/object storage
```

The domain core must not import the HTTP framework, ORM models, database connections, host paths, CUDA libraries, or deployment configuration. It accepts versioned input contracts and returns deterministic result contracts.

## Why Python instead of C++ for P0

- P0 has one spacecraft and bounded station/time horizons rather than a large fleet or high-rate numerical simulation.
- Interval scheduling, exact byte accounting, provenance handling, and persistence are dominated by control flow and data correctness, not dense floating-point throughput.
- Mature orbit libraries already provide optimized low-level operations where needed.
- Python reduces build, FFI, Windows/Linux, and contributor setup friction.
- H100 acceleration does not materially help the current branch-heavy, small-batch workload.

C++ remains an implementation option behind a port only when repeatable profiling on representative scenarios proves that a specific pure-compute component violates an agreed latency budget. Replacing an adapter must not change input/output contracts, canonical serialization, or golden results.

## Portability contract

The supported deployment shapes are:

1. Local development: Python environment plus PostgreSQL 16+.
2. Self-hosted CPU: containerized API and PostgreSQL or an external PostgreSQL service.
3. Team H100 server: the same CPU container; GPU access is not requested.
4. Third-party installation: documented environment variables, database migration command, seed command, CLI smoke test, and HTTP health check.

No code or configuration may depend on the team's hostname, IP address, username, filesystem layout, SSH configuration, or GPU driver.

Container images should target standard Linux amd64 first. Multi-architecture images may be added after the amd64 release path is verified. Host-specific acceleration must be an optional extra rather than the default installation.

## Application boundaries

- Domain core: calculations and policies only.
- Application layer: publish validators, snapshot promotion, run orchestration, and transaction boundaries.
- Persistence adapter: PostgreSQL mapping and migrations; no calculation formulas in triggers or ORM hooks.
- API adapter: request parsing, authentication boundary, response mapping, and OpenAPI; no duplicated calculations.
- CLI adapter: calls the same application use cases as the API.
- Worker process: not required initially. Add only when measured run duration or concurrency requires asynchronous execution.

## Numerical contract

- Logical byte accounting uses integers and exact rational arithmetic.
- Canonical timestamps are UTC with microsecond precision.
- Binary floating-point values are not authoritative for logical capacity or semantic hashes.
- Orbit-provider floating-point output is isolated behind a versioned adapter and quantized according to the accepted result contract.
- The same canonical input and engine manifest must produce the same semantic result hash.

## Persistence contract

> **Superseded on 2026-09-03 by [ADR-0003](ADR-0003-persistence-tiers.md).** The paragraph below
> is the original decision and is kept unedited for the record. PostgreSQL is now an optional
> server tier, the default local store is SQLite, and the calculation CLI needs no database at
> all. Every other clause of this ADR still stands.

PostgreSQL 16+ is the P0 authority because the accepted schema relies on typed constraints, immutable revisions, deferred integrity checks, and deterministic run records. SQLite may be used only for isolated experiments and is not a supported substitute for authoritative P0 persistence.

## Consequences

### Positive

- One implementation serves CLI, API, tests, and UI.
- The project runs without an H100 and remains easy to fork.
- Domain tests can run without a database or web server.
- Native acceleration can be added without rewriting product workflows.

### Negative

- Python will not match optimized native throughput for very large Monte Carlo or fleet workloads.
- Strict module boundaries and immutable contracts require discipline.
- PostgreSQL remains an external runtime dependency for the complete application.

## Revisit conditions

Reconsider native acceleration only if all conditions are met:

1. A representative benchmark and latency target are documented.
2. Profiling identifies a pure-compute hotspot rather than database, serialization, or network overhead.
3. Algorithmic and Python-level improvements are insufficient.
4. A native implementation passes the same golden, property, canonical-hash, and cross-platform tests.

