# Orbit evidence — `EVD-ORB-01` and `EVD-ORB-02`

Everything here exists to answer one question: **do two independently written implementations,
given identical inputs and identical documented settings, produce the same contact windows?**

It is not a claim about real-world orbital accuracy, and nothing here describes KMU-ET02.

> **`EVD-ORB-01` is withheld from the public repository.** It is derived from a CelesTrak-
> redistributed TLE whose public-redistribution terms are unresolved (`Q-ORB-LICENSE-01`), so its
> inputs, provenance, raw element set and GMAT oracle artifacts are kept local only (see the repo
> `.gitignore`). The fully synthetic `EVD-ORB-02` is committed and is the public cross-tool gate;
> its first run is what caught the real IAU-76 axis defect described below. In a public checkout the
> `EVD-ORB-01/` files referenced in this document will be absent and the cross-tool cases for it are
> skipped with an explicit reason, never counted as a pass.

| | `EVD-ORB-01` | `EVD-ORB-02` |
|---|---|---|
| Kind | `GP_TLE` — a real, frozen public TLE | `VIRTUAL_CIRCULAR` — literal initial conditions |
| Object | NORAD 25544 (1998-067A), a public non-mission object | none; a synthetic reference orbit |
| Propagator | SGP4 (Vallado rev 2) | `TWO_BODY_V1`, point-mass only |
| Stations | 4 synthetic sites | 5 synthetic sites |
| Windows | `W1` 24 h, `W2` clipping | `W1` 24 h, `W2` clipping + zero contact |
| Status | **PASS** | **PASS** |

## Who computed what

| Role | Tool | Ships in the product? |
|---|---|---|
| Product engine | `semantix_passbudget.adapters.orbit` on **python-sgp4 2.27** (MIT) | Yes |
| Independent oracle | **NASA GMAT R2026a** (Apache-2.0), `SPICESGP4` + `ContactLocator` | **No.** Offline only; it contributes committed text files and nothing else. |

The two are separate code lineages — python-sgp4 derives from Vallado's C++ reference, GMAT's
`SPICESGP4` from NAIF's SPICE toolkit. They share the *published SGP4 algorithm*, because that is
what SGP4 is; independence here means independent implementations, not independent theories. The
comparison's real strength is over the frame chain, station geodesy, event solving and clipping,
where the two share nothing at all — and that is exactly where it caught a defect (below).

**The oracle is never regenerated from the product engine.** If a delta exceeds a ceiling, the
engine is wrong or the contract is wrong. The expected table is not the thing that changes.

## What the cross-check actually caught

The first `EVD-ORB-02` run failed with AOS deltas up to **22.3 s** against a 1.000 s ceiling.
Isolating the frame chain from the dynamics showed the inertial state agreed with GMAT *exactly*
while the Earth-fixed position was off by **18.29 km**, almost entirely in Z — the size of 26 years
of precession. The cause was a real defect in `twobody.py`: the IAU-76 precession middle rotation
`R2(θ)` had been written as a rotation about X instead of Y. Correcting the axis brought the
Earth-fixed position to within **0.1 m** of GMAT and the fixture to `PASS`.

That defect produced plausible-looking output and would have survived any amount of
self-consistency testing. It is the reason this gate requires a second implementation.

## Files

```
EVD-ORB-01/
  tle_25544.celestrak.raw   the unmodified HTTP response body -- the provenance artifact
  tle_25544.txt             LF-normalised convenience copy
  provenance.json           source URL, retrieval time, hashes, checksum validation, licence status
  inputs.json               stations, windows, propagator profile, Earth and time model
  expected_table.json       the oracle's expected events (generated, never hand-typed)
  delta_table.json          product vs oracle, per pass, with ceilings and worst-case statistics
EVD-ORB-02/
  inputs.json, expected_table.json, delta_table.json
oracle/gmat/
  EVD-ORB-01.script, EVD-ORB-02.script        the mission scripts of record
  EVD-ORB-02-tangent-scan.script              the oracle-only scan that chose the tangent site
  raw/*.report                                unmodified GMAT output, hashed
```

`.gitattributes` marks this tree `-text` so Git cannot rewrite line endings; the recorded SHA-256
values verify byte for byte on checkout.

## Reproducing it

**1. Oracle.** Download NASA GMAT R2026a from the official SourceForge project
(`gmat-win-R2026a.zip`, 403,517,137 bytes,
SHA-256 `f7b00bdeb51e75f5f0a93380a97109f0505e75396f69a43cd5583c21f5fed9fc`) and extract it. It is a
ZIP: no installer, no admin rights, no system changes.

Two preparation steps are required, and both are part of the contract rather than conveniences:

- **Zero the EOP table.** Contract §2 forces UT1−UTC and polar motion to zero in *both* tools, so
  a residual difference measures the implementations rather than two differently-dated IERS
  tables. Replace `data/planetary_coeff/eopc04_08.62-now` with a copy whose x, y, UT1−UTC, LOD,
  dPsi and dEps columns are zeroed, keeping every column width. The generator is
  `scripts/orbit/make_zero_eop.py`.
  Original SHA-256 `eddd4bf62178dad0ff0a5cb500e639a85a2bd54ff507708dbdac7184e2e7159c`;
  zeroed SHA-256 `6426e34cc0531a71c49b420450033e0803226295bda8420aead80cb2be0b3002`.
- **Create `data/gravity/other/`.** The ZIP does not carry empty directories and GMAT refuses to
  initialise without it. This is an extraction artifact, not a configuration choice.

Then run each script and keep the raw reports:

```bash
cd <gmat>/bin && ./GmatConsole.exe --run <repo>/evidence/orbit/oracle/gmat/EVD-ORB-01.script
```

**2. Expected tables.** Parsed from the raw reports, never typed by hand. The converter reads both
GMAT report formats for the same event solution and refuses to emit a table if they disagree:

```bash
python scripts/orbit/gmat_to_expected.py evidence/orbit/oracle/gmat/raw EVD-ORB-01 evidence/orbit/EVD-ORB-01/expected_table.json
```

**3. Comparison.**

```bash
python scripts/orbit/compare_to_oracle.py evidence/orbit/EVD-ORB-01/expected_table.json evidence/orbit/EVD-ORB-01/inputs.json evidence/orbit/EVD-ORB-01/delta_table.json
```

**4. As a test.** The same comparison runs in the suite and needs neither GMAT nor the network,
because the expected tables are committed:

```bash
pytest tests/integration/test_orbit_cross_tool.py
```

## Results

Ceilings are from contract §10.1 and were fixed **before** anything was computed.

| Quantity | Ceiling | Worst `EVD-ORB-01` | Worst `EVD-ORB-02` | Margin |
|---|---|---|---|---|
| Pass count | exact | exact (13 passes) | exact (45 passes) | — |
| AOS | 1.000 s | 0.017031 s | 0.013835 s | 59× |
| LOS | 1.000 s | 0.007365 s | 0.013816 s | 72× |
| Duration | 2.000 s | 0.024554 s | 0.025763 s | 78× |
| Maximum elevation | 0.050° | 0.005075° | 0.004992° | 9.9× |
| Maximum-elevation time | 2.000 s | 0.010703 s | 0.030667 s | 65× |
| Zero-contact stations | exact | agreed | agreed | — |
| Repeat-run difference | 0 | 0 | 0 | — |

Published tolerances, by the rule fixed in contract §10.2
(`min(ceiling, round_up_1sig(10 × worst observed))`), across both fixtures:
**AOS 0.2 s, LOS 0.2 s, duration 0.3 s, maximum elevation 0.05°, maximum-elevation time 0.4 s.**
These document achieved agreement. The gate is the ceiling, never these.

## Coverage

| Required case | `EVD-ORB-01` | `EVD-ORB-02` |
|---|---|---|
| Multiple ordinary passes | 11 in `W1` | 42 in `W1` |
| Pass clipped at window start | `W2`, MIDLAT | `W2`, MIDLAT |
| Pass clipped at window end | `W2`, MIDLAT | `W2`, MIDLAT |
| Station with no contact | `SYN-GS-POLAR`, analytically guaranteed | 3 stations in `W2` |
| Low maximum elevation | 7.33° | 7.41° |
| Tangent pass (< 0.5° above mask) | `SYN-GS-GRAZE`, 5.4915° | `SYN-GS-TANGENT`, **5.0476°** |

`EVD-ORB-01`'s zero-contact case is an analytic guarantee: an 85° N station is 33.37° from the
51.6312° ground-track limit against a 15.82° visibility half-angle, so no propagator may find a
pass. `EVD-ORB-02` has no such guarantee — at 98° inclination the ground track reaches every
latitude — so its zero-contact case comes from the short `W2` window instead, and that difference
is stated rather than glossed over.

## Limitations, stated

- Forcing UT1−UTC to zero displaces Earth rotation by up to ±0.9 s relative to the real Earth.
  These fixtures certify **agreement between two implementations on one defined problem**, not
  absolute real-world AOS/LOS.
- No refraction, no light-time, no stellar aberration, no azimuth-dependent horizon mask.
- Station coordinates are synthetic. **No result here is KMU-ET02 performance.**
- `EVD-ORB-02`'s frame chain uses a truncated IAU-1980 nutation series; the residual is under
  0.1 arcsecond, worth under 0.5 ms of pass timing against a 1.000 s ceiling.
- The CelesTrak redistribution terms for the frozen TLE are recorded as an open item
  (`Q-ORB-LICENSE-01`) and must be confirmed by the project owner before public release.
