# ADR-0004: Orbit engine, independent oracle, and the JVM question

- Status: **ACCEPTED — option C, 2026-09-03** (`Q-ORB-RUNTIME-01` resolved by PM)
- Update (2026-09-04): the `ORBIT_DERIVED` domain gate is now **open**. python-sgp4 was promoted
  from an optional extra to a core dependency (it is required for the core user flow), and the
  engine manifest's orbit revisions are real values on an `ORBIT_DERIVED` run. The adapter-boundary
  rules below are unchanged and still enforced by `tests/unit/test_architecture.py`.
- Date: 2026-09-03
- Supersedes nothing. Extends ADR-0001 (`Portability contract`, `Numerical contract`) and
  ADR-0002 (`contact_source` provenance).

## Context

`ORBIT_RELEASE_GATE.md` keeps P0 at `P0_RELEASE_BLOCKED_NEEDS_EVIDENCE` because no production
orbit provider exists and no independent oracle has produced an expected event table. The gate
cannot be opened by writing an SGP4 adapter alone: §25.10 of the golden design document forbids
verifying a production implementation against itself, so a *second, independent* implementation is
a hard prerequisite.

The proposed split is:

| Role | Tool | Enters the shipped product? |
|---|---|---|
| Product engine | Orekit (via `orekit_jpype`) | Yes — that is the decision under review |
| Independent oracle | NASA GMAT | **No.** Used offline to generate a static expected table that is committed as data. |

The oracle half raises no product-architecture question: GMAT never becomes a dependency, is never
imported, and contributes only committed text files. The product half does raise one, and ADR-0001
does not settle it.

## The conflict

ADR-0001 fixes a **Python, CPU-first** runtime and a portability contract that forbids depending on
host layout. `README.md` states the installation contract more strongly still:

> Python 3.12 is required. Nothing else is: no PostgreSQL, no Docker, no network service.

Orekit is a Java library. Adopting it as the *product* engine breaks that sentence. The break is not
a licence problem in itself — the licences are compatible — it is a runtime and distribution
problem. The facts, gathered from package metadata on 2026-09-03:

| Component | Version | Licence | Size | Note |
|---|---|---|---|---|
| `orekit_jpype` | 13.1.7.1 | Apache-2.0 | 12.13 MiB wheel | Pure-Python bridge plus the Orekit JARs |
| `jpype1` | ≥ 1.7.1 | Apache-2.0 | — | CPython↔JVM bridge; compiled extension |
| `jdk4py` (optional) | 25.0.2.1 | **GPL-2.0** (classifier) | 29.55 MiB per platform | A packaged OpenJDK build |
| `orekit-data` | n/a | separate terms | tens of MiB | Required at runtime; not on PyPI |

Apache-2.0 is compatible with this project's MIT licence. It is *not* silent, though: §4(d)
requires that a `NOTICE` file, if present in the distributed work, be reproduced. A repository that
ships Orekit and has no `NOTICE` is out of compliance, so adopting Orekit adds a `NOTICE`
obligation regardless of which runtime option is chosen.

The JVM itself is the real fork in the road, and there are only three ways to get one:

### Option A — require a system JDK

The developer or operator installs a JDK; the product finds it.

- Breaks the README installation contract outright.
- Breaks reproducibility in a way that matters for this project specifically: the engine manifest
  is supposed to pin what computed a result, and an uncontrolled host JDK means two machines can
  produce two results under one manifest. That is the exact failure mode `engine_manifest` exists
  to prevent.
- Verified on this machine: Java 21.0.7 LTS is present. That is *why* it is dangerous — it would
  have worked here and failed silently elsewhere.

### Option B — bundle `jdk4py`

`pip install` pulls a platform-specific OpenJDK wheel.

- Restores single-command installation and pins the JVM, so reproducibility is recovered.
- Costs ~30 MiB per platform and makes the wheel platform-specific, where the project is currently
  pure-Python and platform-neutral.
- **Licence flag.** `jdk4py` is classified GPL-2.0 on PyPI. OpenJDK is GPLv2 **with the Classpath
  Exception**, which is designed to permit exactly this kind of bundling without imposing GPL terms
  on the surrounding work. The PyPI classifier does not record the exception. This ADR does not
  assert the conclusion either way: an MIT project acquiring a GPLv2-classified dependency is a
  decision for the project owner, and it must be made by reading the actual `LICENSE` and
  `ASSEMBLY_EXCEPTION` files in the shipped artifact, not a PyPI classifier.

### Option C — keep Java out of the product

Orekit is used, but only as a second *offline* cross-check alongside GMAT, and the shipped engine
is a pure-Python SGP4 implementation validated against **both**.

- Preserves ADR-0001 and the README contract exactly.
- Costs an extra implementation, and moves Orekit from "product engine" to "second oracle" — which
  is arguably a better use of it, because two independent oracles bound the product tighter than
  one.
- Does **not** violate the self-verification prohibition: the product would be verified by GMAT and
  Orekit, neither of which is the product.

## Decision

**Option C, accepted by PM on 2026-09-03.** Java stays out of the product. The shipped engine is
pure Python; Orekit is demoted from product-engine candidate to an available offline oracle, and
GMAT is the oracle actually used.

The product engine is **python-sgp4 2.27**, chosen because it satisfies every constraint that made
Orekit problematic:

| Constraint | python-sgp4 2.27 |
|---|---|
| Licence | **MIT** — the project's own licence, so no `NOTICE` obligation is introduced |
| Runtime | Pure Python; ships a `py3-none-any` wheel alongside optional accelerated builds |
| Size | 120 KiB pure wheel, against 12 MiB of Orekit JARs plus ~30 MiB of JVM |
| Runtime data | None. No EOP bundle, no gravity models, no network access |
| Algorithm | Vallado's revised *Spacetrack Report #3*, which is exactly what contract §5 specifies |

It is added as an **optional extra** (`pip install semantix-passbudget[orbit]`), not a core
dependency, so `README.md`'s "Python 3.12 is required. Nothing else is" stays literally true while
the `ORBIT_DERIVED` domain gate is still closed. Verified: a clean-install of the wheel does not
pull `sgp4`, and `verify-golden` from that install produces byte-identical hashes. Promoting it to
a core dependency is a one-line change when the domain gate opens.

**The independence requirement is still met.** python-sgp4 and GMAT's `SPICESGP4` are separate
code lineages (Vallado's C++ reference and NAIF's SPICE toolkit). They share the published SGP4
algorithm because that is what SGP4 *is*; independence here means independent implementations, not
independent theories. The cross-check's real power lies in the frame chain, station geodesy, event
solving and clipping, where the two share nothing — and that is precisely where it caught a real
defect: an IAU-76 precession rotation applied about the wrong axis, producing an 18.29 km
Earth-fixed error and 22.3 s AOS deltas. See `evidence/orbit/README.md`.

What *would have held* under all three options, and does hold now:

1. **The oracle is GMAT, and GMAT never ships.** It contributes committed static data only.
2. **`docs/specs/ORBIT_VERIFICATION_CONTRACT.md` is engine-independent.** Every definition,
   window, mask and tolerance in it was fixed before any engine was chosen, so none of the three
   options can change what "correct" means.
3. **The adapter boundary is fixed** (see below), so the choice among A/B/C changes one adapter
   and nothing above it.
4. **No orbit engine is added to `pyproject.toml` runtime dependencies** until this ADR is
   accepted. An evaluation dependency, if any, lives in an optional extra that the product does not
   import.

## Integration shape, if a JVM is adopted (A or B)

Three shapes were considered: a long-lived Java sidecar service, a subprocess CLI invoked per run,
and an in-process bridge via JPype.

| | Sidecar service | Subprocess CLI | In-process JPype |
|---|---|---|---|
| Isolation | Strong: separate process and address space | Strong: fresh process per run | **None**: a JVM crash takes the API process with it |
| Deployment complexity | Highest: a second service to start, health-check, version and secure | Moderate: one executable to locate | Lowest: `pip install` |
| Reproducibility | Good, if the image pins the JVM | Good, if the image pins the JVM | Good |
| Failure semantics | Network errors, timeouts, partial responses | Exit code, stdout/stderr, timeout — all structured and easy to bound | Java exceptions surface as Python exceptions |
| Startup cost | Amortised | JVM start (~0.5–1 s) per invocation | Once per process |
| New attack surface | A listening socket | None | None |

**Recommended shape: in-process JPype**, and the reasoning is that the usual argument for isolation
does not apply here. A sidecar or subprocess buys isolation from a crashing or hanging engine; the
price is a second deployment artifact, a socket or an executable path, and a whole class of
"where is it?" failures that ADR-0001 forbids depending on. But P0 runs one satellite over a
bounded window and the workload is small and deterministic, so the crash risk being insured against
is largely hypothetical, while the deployment complexity is certain. A sidecar would also
reintroduce exactly the "no network service" dependency the README rules out.

If the JVM is adopted, in-process JPype with a strict adapter boundary is the shape that costs
least and breaks fewest existing guarantees. The isolation that a sidecar would have provided is
recovered more cheaply by the error contract below.

## Adapter boundary (binding under every option)

This is the part that must not depend on the outcome, so it is decided now.

- `ports/contact_provider.py` stays exactly as it is. The orbit provider is a second implementation
  of the existing `ContactProvider` protocol, not a new port shape.
- No module under `domain/` or `application/` may import the engine, its bridge, or any symbol from
  it. `tests/unit/test_architecture.py` already enforces the equivalent rule for SQLAlchemy and
  must be extended to cover the orbit engine.
- The provider is selected by the composition root only, and only for
  `contact_source = ORBIT_DERIVED`.
- `SyntheticContactProvider` is **not** removed, **not** wrapped and **not** modified. It remains
  the `SYNTHETIC_INJECTED` provider, and the two never share a code path.
- **No fallback.** If the orbit provider fails, the run fails with a structured error. Falling back
  to synthetic contacts would silently relabel a synthetic result as an orbit result, which is the
  single most dangerous failure this project can have.
- Engine failure, timeout, and unparseable output each map to a distinct structured error code and
  never to a partial result.
- Errors must not leak a filesystem path, an environment variable, a JVM classpath or a host name —
  the existing redaction rule in `tests/unit/test_error_redaction.py` extends unchanged.
- Floating-point state stays inside the adapter at full double precision; quantisation to canonical
  microseconds happens exactly once, on the way out, per ADR-0001's numerical contract.
- Engine version, data-bundle revision and propagator profile are recorded in `ENGINE_MANIFEST` as
  real values. The current `NOT_APPLICABLE` placeholders may only be replaced with values actually
  read from the running engine — never hard-coded strings.

## Data bundle

Any Orekit-based path additionally requires an `orekit-data` bundle (UTC-TAI history, EOP, gravity
models). Under the verification contract, UT1−UTC and polar motion are forced to zero and no EOP
table participates in the calculation, which materially shrinks what must be vendored — but the
bundle's provenance, version and SHA-256 must still be pinned and committed, and it must never be
fetched at runtime. This is unresolved until the option is chosen.

## Consequences

### If A or B is accepted
- `README.md`'s installation contract must be rewritten; it is currently false under either.
- A `NOTICE` file becomes mandatory (Apache-2.0 §4(d)).
- The Docker image grows by the JVM; the wheel becomes platform-specific under B.
- Under B, the GPLv2-classified dependency must be reviewed and the conclusion recorded.

### If C is accepted
- ADR-0001 and the README stand unchanged.
- A pure-Python SGP4 must be written and validated against two independent oracles.
- Orekit and GMAT both become offline oracles; neither ships.

### Under all options
- The verification contract is unaffected.
- `ORBIT_DERIVED` was refused with `UNSUPPORTED_CONTACT_SOURCE` until a delta table existed. The
  delta table now exists (`EVD-ORB-02`) and the gate is open; the refusal was replaced by the
  ADR-0002 provenance-split validation (see `ORBIT_RELEASE_GATE.md`).

## Revisit conditions

- `Q-ORB-RUNTIME-01` is decided.
- `Q-DATA-03` selects the `VIRTUAL_CIRCULAR` propagator profile.
- A GMAT expected table and a cross-tool delta table exist for both `EVD-ORB-01` and `EVD-ORB-02`.
