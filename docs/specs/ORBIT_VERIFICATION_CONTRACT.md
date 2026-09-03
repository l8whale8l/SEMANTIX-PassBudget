# Orbit verification contract — `EVD-ORB-01` / `EVD-ORB-02`

> Status: **FROZEN BEFORE COMPUTATION**
> Frozen on: 2026-09-03
> Authority: `골든시나리오설계도.md` §25.10–§25.11, `P0_FUNCTIONAL_SPEC.md` §14, `ORBIT_RELEASE_GATE.md`

This document exists so that no tolerance, window, mask or definition can be chosen after seeing a
number. Every clause below was written while the repository contained **no** orbit engine, **no**
oracle output and **no** expected event table. The frozen TLE was retrieved and hashed before this
document was written; nothing has been propagated from it.

Anything not fixed here is **not yet decided**, and a comparison that depends on it may not be run.

---

## 1. Independence rule

| Role | Tool | Constraint |
|---|---|---|
| Product engine | `semantix_passbudget.adapters.orbit`, built on **python-sgp4 2.27** (MIT; Vallado revised *Spacetrack Report #3*) | Ships in the product. Pure Python, no JVM, no runtime data files, no network. |
| Independent oracle | **NASA GMAT R2026a** (Apache-2.0), `SPICESGP4` propagator and `ContactLocator` | Never linked into the product, never imported at runtime, never a package dependency. Used solely to generate a static expected table. |

Resolved by PM decision on 2026-09-03 (`Q-ORB-RUNTIME-01`, option C in `ADR-0004`): Orekit is **not**
the product engine, because a JVM contradicts ADR-0001's Python-CPU-first portability contract.
Orekit remains available as an *additional offline oracle*; it never ships.

The two implementations are independent code lineages — python-sgp4 derives from Vallado's C++
reference, GMAT's `SPICESGP4` from NAIF's SPICE toolkit. They necessarily share the *published SGP4
algorithm*, because that is what SGP4 is; independence here means independent implementations, not
independent theories, and the comparison's real power is over the frame transformation, station
geodesy, event solving and clipping, where the two share nothing.

Product-engine output may **never** be used to verify product-engine output. A test whose expected
values were produced by the product engine is not evidence and must not be counted toward this gate.

Neither tool's configuration may be changed after its counterpart's numbers are known, except by
amending this document with a dated entry in §12 stating what changed and why.

---

## 2. Time

| Item | Fixed value |
|---|---|
| Time scale for all inputs and all reported events | **UTC** |
| Timestamp format | `YYYY-MM-DDTHH:MM:SS.ffffffZ`, exactly six fractional digits |
| Leap seconds | No event may be placed in a leap-second window. A `:60` second is refused, never shifted. Matches `domain/time.py`. |
| UT1 − UTC | **Forced to 0.0 s in both tools.** |
| Polar motion (x_p, y_p) | **Forced to 0.0 in both tools.** |
| Leap-second / EOP data file | **Not used.** Because UT1−UTC and polar motion are forced to zero, no EOP or leap-second table participates in the calculation, and there is therefore no EOP data hash to record. This is a deliberate simplification recorded as a limitation, not an omission. |
| Internal computation precision | IEEE-754 double throughout the adapter. Quantisation to microseconds happens **once**, at the adapter boundary, on the way out. |
| Quantisation rule | Half-even to whole microseconds, matching `time_quantization_revision = UTC_US_HALF_EVEN_V1`. |

**Why UT1−UTC and polar motion are forced to zero.** The two tools would otherwise consult
different EOP tables retrieved on different dates, and the resulting disagreement would measure the
tables, not the implementations. Zeroing both makes the TEME→ITRF transformation analytically
identical in the two tools, so a residual difference is attributable to the propagator and the event
solver, which is what this fixture is meant to measure.

**What this costs.** Forcing UT1−UTC to zero displaces the Earth's rotation by up to ±0.9 s of
rotation angle relative to the true Earth. This fixture therefore does **not** certify absolute
pointing or real-world AOS/LOS to better than that. It certifies that two independent
implementations agree on the same defined problem. This limitation must be restated wherever the
result is published.

---

## 3. Frames

| Item | Fixed value |
|---|---|
| Propagation output frame | **TEME of date** — the only frame in which an SGP4 state is defined |
| Earth-fixed frame | **ITRF**, reached from TEME by sidereal rotation alone, with polar motion zeroed per §2 |
| Sidereal angle | GMST, IAU-82 / FK5 convention, as used by the standard SGP4 TEME→PEF rotation |
| Station position | Fixed in the Earth-fixed frame |
| Topocentric frame | East–North–Up at the station's geodetic position |
| Elevation | Angle above the local **geodetic** horizon plane (normal to the ellipsoid), **not** the geocentric horizon |
| Light-time / aberration | **Not applied.** Geometric elevation only. |

---

## 4. Earth model and constants

| Item | Fixed value |
|---|---|
| Ellipsoid | **WGS-84** |
| Semi-major axis `a` | 6 378 137.0 m (exact, by definition) |
| Flattening `f` | 1 / 298.257223563 (exact, by definition) |
| Gravitational model used by the propagator | **WGS-72**, as required by standard SGP4 |
| Station height datum | **Ellipsoidal height** (height above the WGS-84 ellipsoid), never orthometric/MSL. No geoid model is applied. |

**The two ellipsoids are deliberate, not an inconsistency.** SGP4 is defined against WGS-72
constants and produces a wrong orbit if fed WGS-84 ones; station geodesy is defined in WGS-84.
Both tools must be configured this way, and any tool that cannot separate them is disqualified as
an oracle.

---

## 5. Propagation model

| Item | Fixed value |
|---|---|
| `EVD-ORB-01` propagator | **SGP4/SDP4 as published in Vallado's revised *Spacetrack Report #3* ("SGP4 rev 2")**, the near-Earth SGP4 branch being selected automatically by the standard period test |
| Input of record | The two literal TLE lines in `evidence/orbit/EVD-ORB-01/tle_25544.celestrak.raw` |
| Element re-fitting, averaging or osculating conversion | **Forbidden.** The TLE is fed to SGP4 unmodified. |
| Additional forces | **None.** SGP4 is a complete theory; adding drag, SRP or a gravity field to it is an error. |
| `EVD-ORB-02` propagator | **`TWO_BODY_V1`** — point-mass gravity only, resolved by PM decision on 2026-09-03 (`Q-DATA-03`). See §7.2. |

---

## 6. Stations, mask and refraction

| Item | Fixed value |
|---|---|
| Geodetic reference | WGS-84 geodetic latitude, **east-positive** longitude, ellipsoidal height in metres |
| Minimum elevation mask | **Constant 5.000000°** for every station in both fixtures |
| Azimuth-dependent horizon mask | **Not modelled** in P0 (registered as a P1 item) |
| Atmospheric refraction | **Not applied.** Both tools must have refraction explicitly disabled. |
| Station availability | Assumed always available. This is a PROXY assumption and is labelled as such. |

**Refraction is off, not defaulted off.** Refraction raises an apparent low-elevation target by
roughly 0.1–0.2° near a 5° mask, which moves AOS by seconds — larger than the entire tolerance
budget. A tool left at a refraction default would silently dominate the delta table, so each tool's
refraction setting must be explicitly recorded in its configuration artifact.

### 6.1 Station coordinates are synthetic

No verified KMU-ET02 coordinate exists in this repository or in any parent design document. Every
station below is a **synthetic verification coordinate chosen for geometric coverage**. It is not a
KMU site, and no result computed from it may be presented as KMU-ET02 performance.

| Station key | Latitude (deg, +N) | Longitude (deg, +E) | Ellipsoidal height (m) | Why it is in the fixture |
|---|---|---|---|---|
| `SYN-GS-MIDLAT` | +37.600000 | +127.000000 | 100.000 | Mid-latitude; yields several passes per day against an ISS-like inclination |
| `SYN-GS-EQUATOR` | +0.000000 | +60.000000 | 0.000 | Equatorial; yields a different pass mix including low-culmination passes |
| `SYN-GS-POLAR` | +85.000000 | +0.000000 | 0.000 | **Guaranteed zero-contact case.** A 51.6312° inclination orbit cannot raise the satellite above a 5° mask at 85° N, so this station must return no contact in any window. This is an analytic guarantee, not an observation. |
| `SYN-GS-GRAZE` | +67.200000 | +0.000000 | 0.000 | **Tangent-pass coverage** (added 2026-09-03, see §12). Placed just inside the visibility circle so its best possible pass grazes the mask. Chosen from geometry alone, before any pass for it was computed: the ground track reaches ±51.6312° latitude and the 5°-mask visibility half-angle is 15.8223°, so the northernmost station that can see anything at all is at 67.4535° N. At 67.2° N the minimum central angle is 15.5688°, giving a best-case elevation of 5.33° — 0.33° above the mask, inside the §8.7 tangent band. If it yields no pass at all it simply becomes a second zero-contact station, which is also valid coverage. |

---

## 7. Analysis windows and fixture inputs

### 7.1 `EVD-ORB-01` (GP_TLE)

| Item | Fixed value |
|---|---|
| Primary window `W1` | `2026-09-03T06:00:00.000000Z` → `2026-09-04T06:00:00.000000Z` (exactly 24 h) |
| Window convention | Half-open `[start, end)`, matching `domain/time.py` `TimeInterval` |
| Relation to epoch | Window opens 1 h 46 min 38.9136 s after the TLE epoch and closes 25 h 46 min after it, so SGP4 is used within a propagation span where a GP element set is meaningful |

**Boundary-clipping coverage.** A window boundary that falls inside a pass is required coverage
(§8.4). Whether `W1` happens to produce one is a geometric fact not yet known, because nothing has
been propagated. The protocol is fixed now:

> If `W1` contains no pass straddling either boundary, a second window `W2` shall be defined from
> the **independent oracle's** `W1` output — never from the product engine.

Deriving fixture geometry from the oracle rather than from the product engine keeps the product
engine from shaping the test it must later pass. `W2` is a coverage device; it does not change any
tolerance.

**`W2`, resolved 2026-09-03.** The `W1` oracle run produced no boundary-straddling pass (first AOS
12:05, last LOS 04:17, both well inside the 06:00–06:00 window), so `W2` was derived by this rule:

> `W2 = [ ceil_to_minute(t_c1), ceil_to_minute(t_c2) )`, where `t_c1` and `t_c2` are the
> maximum-elevation times of the **first and second `SYN-GS-MIDLAT` passes in `W1` as reported by
> GMAT**, each rounded **up** to the next whole minute.

| Quantity | Oracle value | Rounded |
|---|---|---|
| `t_c1` | `2026-09-03T12:08:24.489Z` | `2026-09-03T12:09:00.000000Z` |
| `t_c2` | `2026-09-03T13:44:55.067Z` | `2026-09-03T13:45:00.000000Z` |

so **`W2` = `2026-09-03T12:09:00.000000Z` → `2026-09-03T13:45:00.000000Z`**.

This yields exactly the two missing cases at once: the first pass (12:05:05.997 → 12:11:43.454) is
**clipped at the start**, and the second (13:40:44.234 → 13:49:06.861) is **clipped at the end**.

The rounding to a whole minute is not cosmetic. Setting a boundary exactly on a culmination time
would make the clipped pass's maximum elevation a supremum that the half-open interval never
attains, so the two tools would be compared on a quantity that is not well defined. Rounding up
moves `t_c1` outside its pass's peak (the clipped interval's maximum is then attained at the closed
start boundary) and keeps `t_c2` strictly inside its pass (the maximum is a genuine interior
maximum). Both compared values are then attained.

### 7.2 `EVD-ORB-02` (VIRTUAL_CIRCULAR) — inputs fixed, propagator blocked

Every initial condition is literal. No tool default may supply any of them.

| Item | Fixed value |
|---|---|
| Epoch | `2026-09-03T00:00:00.000000Z` (UTC) |
| State type | Keplerian, **osculating**, defined in **EME2000 (J2000)** |
| Semi-major axis `a` | 6 378 137.0 m + 700 000.0 m = **7 078 137.0 m** exactly |
| Eccentricity `e` | **0.0** exactly |
| Inclination `i` | **98.000000°** |
| RAAN Ω | **90.000000°** |
| Argument of perigee ω | **0.000000°** (degenerate for `e = 0`; fixed to 0 so both tools receive the same literal) |
| True anomaly ν | **0.000000°** |
| Central body μ | **3.986004415 × 10¹⁴ m³/s²** (EGM-96 / DE-consistent value), stated explicitly because tool defaults differ in the last digits |
| Analysis window | `2026-09-03T00:00:00.000000Z` → `2026-09-04T00:00:00.000000Z` (exactly 24 h) |
| Stations | The same three synthetic stations in §6.1, same 5° mask |
| Propagator | **`TWO_BODY_V1`** — resolved by PM decision on 2026-09-03 (see §12). |

`Q-DATA-03` must select exactly one of these two profiles, and both tools must then be configured
to it:

- **Profile `TWO_BODY_V1`** — point-mass gravity only. No J2, no drag, no SRP, no third body.
  Perfectly reproducible; the orbit does not precess, so the RAAN stays at 90° and the pass pattern
  repeats cleanly.
- **Profile `J2_ONLY_V1`** — point mass plus the J2 zonal term only, with
  `J2 = 1.0826298213 × 10⁻³` and `R_ref = 6 378 137.0 m` stated literally. Physically closer to a
  real sun-synchronous orbit; requires both tools to use the identical J2 and reference radius.

**Resolved 2026-09-03: `TWO_BODY_V1`.** Point-mass gravity is analytically exact, so any
disagreement between the two tools on this fixture is unambiguously an implementation defect. Under
`J2_ONLY_V1` a disagreement could instead mean the two tools were configured with different J2 or
reference-radius values, which would make the fixture measure configuration rather than code. The
physical realism `J2_ONLY_V1` would add is not what this fixture is for: `EVD-ORB-01` already
carries the realistic case.

---

## 8. Event definitions

### 8.1 AOS and LOS

- Let `E(t)` be geometric elevation, degrees, per §3 and §6.
- **AOS** is the instant `t_a` where `E(t)` crosses the mask **upward**: `E(t_a) = 5.000000°` with
  `dE/dt > 0`.
- **LOS** is the next instant `t_l > t_a` where `E(t)` crosses the mask **downward**:
  `E(t_l) = 5.000000°` with `dE/dt < 0`.
- A contact is the half-open interval `[t_a, t_l)`, matching the codebase's interval convention.
- `duration = t_l − t_a`, reported in whole microseconds.
- Event root-finding must converge to **≤ 1 × 10⁻⁶ s** in both tools, so the solver tolerance is at
  least three orders of magnitude below the §10 acceptance ceiling and cannot dominate the delta.

### 8.2 Maximum elevation and its time

- `max_elevation` is `max E(t)` over the **reported (post-clipping) contact interval**, in degrees.
- `max_elevation_time` is the `t` attaining it.
- Both are reported for every contact, including a clipped one — in which case both are taken over
  the clipped interval, so a clipped pass reports the peak that is actually inside the window, not
  the peak of the unclipped pass. This is stated because the two readings differ and either is
  defensible; the fixture uses the clipped reading.
- Reported to **6 decimal places** of a degree (µdeg), matching `maximum_elevation_udeg`.

### 8.3 Sampling and search

Neither tool may report an event found only by coarse sampling. Each tool shall step at **≤ 10 s**
to bracket a mask crossing, then refine to the §8.1 tolerance. A 10 s bracket cannot skip a pass:
the shortest geometrically possible 5°-mask pass for these orbits is on the order of a minute.

### 8.4 Window clipping

- A pass entirely outside `[W_start, W_end)` is **not reported**.
- A pass straddling `W_start` is reported with `aos = W_start`, flagged `clipped_start = true`, and
  `aos_is_true_crossing = false`.
- A pass straddling `W_end` is reported with `los = W_end`, flagged `clipped_end = true`, and
  `los_is_true_crossing = false`.
- A clipped boundary **is never compared as a crossing time**. Comparing `W_start` against
  `W_start` is a tautology. For a clipped pass, the compared quantities are the *unclipped* side,
  the duration, and the in-window maximum elevation.
- Because the window is half-open, an event exactly at `W_start` is **inside**; an event exactly at
  `W_end` is **outside**.

### 8.5 Exact-boundary events

If a computed crossing lands within **1 µs** of `W_start` or `W_end` after quantisation, the case is
**escalated, not resolved by rounding**: the comparison run fails with `BOUNDARY_AMBIGUOUS` and this
document must be amended to state the chosen rule before the gate may open. A tie broken silently at
the boundary is exactly the class of defect this fixture exists to catch.

### 8.6 No contact

A station–window pair with no pass is a **first-class expected result**, written as an explicit
empty list, never as an absent record. `SYN-GS-POLAR` must produce it (§6.1). An oracle table that
simply omits that station is incomplete and fails the gate.

### 8.7 Tangent and low-elevation passes

- A pass whose maximum elevation exceeds the mask by **< 0.5°** is a *tangent pass*.
- A tangent pass is reported normally; it is **not** filtered out.
- Tangent passes are compared under the same §10 ceiling as any other pass. If a tangent pass is the
  sole cause of a ceiling breach, that fact is reported explicitly rather than excluded, because
  near-tangency is where AOS/LOS timing is intrinsically worst-conditioned (`dE/dt → 0`) and that
  conditioning is a real property of the product, not a nuisance.
- A pass that only touches the mask without crossing it (`max E(t) = 5.000000°` to solver tolerance,
  never exceeding) is **not** a contact: `[t_a, t_l)` would be empty, and `domain/time.py` refuses a
  zero-length interval.

---

## 9. Contact identity, ordering and determinism

| Item | Fixed rule |
|---|---|
| Sort key | `(aos, los, station_key, stable_key)` ascending — identical to `SyntheticContactProvider`, so provider swaps cannot reorder results |
| `stable_key` | `ORB-{fixture_id}-{station_key}-{aos in YYYYMMDDTHHMMSSffffff}` — derived only from fixed inputs, so it is stable across runs, machines and OSes |
| Pass correspondence in the delta table | Matched by `(station_key, ordinal within station)`, **not** by nearest time. Nearest-time matching can silently pair pass *n* with pass *n+1* and hide a missing pass as a small delta. |
| Count mismatch | If the two tools disagree on pass count for any station, the comparison **stops and fails**. No partial delta table is produced from a mismatched pairing. |
| Determinism | Each engine is run **twice** in the same process-fresh state; byte-identical output is required. A non-deterministic engine fails the gate regardless of its accuracy. |

---

## 10. Tolerances, fixed in advance

§25.11 states that ±1 s is *an initial target, not an approval criterion*, and that the released
tolerance must be backed by the observed inter-implementation error budget. Both halves are honoured
by separating two distinct numbers, **both fixed now**:

### 10.1 Acceptance ceiling — the gate decision

The gate opens only if every quantity below stays within its ceiling. These numbers are **fixed
before any computation** and may not be widened afterwards for any reason.

| Quantity | Ceiling | Derivation |
|---|---|---|
| Pass count per station | Exact equality | Not a tolerance; a count is either right or wrong |
| AOS delta (unclipped side) | **≤ 1.000 s** | See error budget below |
| LOS delta (unclipped side) | **≤ 1.000 s** | Same budget |
| Duration delta | **≤ 2.000 s** | Two independent endpoints, each within 1.000 s |
| Max-elevation delta | **≤ 0.050°** | At a typical ISS-pass elevation rate near the mask (≈ 0.05–0.10 °/s), 0.05° corresponds to well under 1 s, so this is consistent with the timing ceiling rather than a separate looser claim |
| Max-elevation-time delta | **≤ 2.000 s** | Deliberately looser: near culmination `dE/dt → 0`, so the peak *time* is intrinsically ill-conditioned even when the peak *value* agrees closely. This is geometry, not implementation error. |
| Zero-contact stations | Exact agreement | Both tools must report the empty list |
| Repeat-run difference | **0** (byte-identical) | Determinism is not a tolerance |

**Error budget behind the 1.000 s timing ceiling.** With the same TLE, the same SGP4 theory, the
same WGS-72 propagation constants, refraction off, and UT1−UTC and polar motion both forced to zero
(§2), the surviving sources of disagreement are:

| Source | Bound | Reasoning |
|---|---|---|
| Event root-finder | ≤ 1 × 10⁻⁶ s | Both solvers are required to converge to this (§8.1) |
| SGP4 arithmetic implementation | ≲ 1 × 10⁻³ s | Both are Vallado-rev-2 derivations; published cross-implementation position agreement is sub-metre near epoch, and a metre of along-track error maps to ≈ 1.3 × 10⁻⁴ s of pass timing at 7.66 km/s |
| GMST formulation rounding | ≲ 1 × 10⁻² s | Same IAU-82 series; differences are in the last coefficient digits |
| Geodetic latitude / station height conversion | ≲ 1 × 10⁻² s | Both use closed-form or converged WGS-84 conversions |
| **Total expected** | **≪ 0.1 s** | |

The 1.000 s ceiling is therefore roughly an order of magnitude above the largest disagreement the
physics permits. It is a **conservative upper bound chosen so that a breach means a real defect**,
not a target the implementations are expected to just barely meet.

### 10.2 Published tolerance — documentation of achieved agreement

After the comparison runs, the published tolerance is derived by a rule fixed now:

```text
published_tolerance = min( ceiling , round_up_to_1_significant_figure( 10 x max_observed_delta ) )
```

This is **documentation, never the gate**. The gate is §10.1 alone. The published number may only
ever be *tighter* than the ceiling, never looser, so this rule cannot be used to rescue a failing
run. If `max_observed_delta` exceeds the ceiling, there is no published tolerance — there is a
failure.

### 10.3 What is forbidden

- Widening any §10.1 ceiling after seeing a delta.
- Editing the oracle's expected table so the product matches it.
- Excluding a pass from the delta table because it is inconvenient.
- Reporting a skipped or unexecuted comparison as a pass.
- Reporting agreement between Orekit and Orekit as cross-tool evidence.

---

## 11. Open decisions that block the gate

| ID | Decision | Owner | Blocks |
|---|---|---|---|
| ~~`Q-DATA-03`~~ | **Resolved 2026-09-03: `TWO_BODY_V1`** (§7.2) | Orbit/Backend + V&V | — |
| `Q-ORB-LICENSE-01` | CelesTrak redistribution terms for the frozen TLE in a public repository | PM / legal | Publishing `EVD-ORB-01` |
| ~~`Q-ORB-RUNTIME-01`~~ | **Resolved 2026-09-03: option C** — Java stays out of the product; the engine is pure-Python SGP4 and Orekit is demoted to an offline oracle (`ADR-0004`) | PM | — |

---

## 12. Amendment log

| Date | Clause | Change | Reason |
|---|---|---|---|
| 2026-09-03 | — | Initial freeze, before any orbit computation existed in the repository | Prevents post-hoc tolerance fitting |
| 2026-09-03 | §7.1 | `W2` resolved to `12:09:00Z → 13:45:00Z` by a stated rule over the oracle's `W1` output | The `W1` protocol was triggered: no `W1` pass straddled a boundary, so the required clipping coverage did not exist. The replacement rule uses oracle output only. **No tolerance was touched.** |
| 2026-09-03 | §7.2, §11 | `Q-DATA-03` resolved to `TWO_BODY_V1`; `Q-ORB-RUNTIME-01` resolved to option C | PM decisions taken on the record before either `EVD-ORB-02` number existed. **No tolerance was touched.** |
| 2026-09-03 | §6.1 | Added station `SYN-GS-GRAZE` at 67.2° N | `W1`'s lowest culmination was 7.33°, so the §8.7 tangent case had no coverage. The latitude was derived from the orbit's inclination and the mask's visibility half-angle **before** any pass for it was computed, so it is a geometric choice, not a fitted one. **No tolerance was touched.** |
