// Display-only orbit sampling for the globe view (F5).
//
// The backend does not emit a satellite trajectory (only AOS/LOS contact windows), so to *draw* the
// orbit we re-sample the SAME `orbit.two_body` elements the run was computed from. This changes
// nothing the engine produced: contact windows still come from the backend result and gate the
// connection lines; this module only paints where the assumed satellite is between those windows.
//
// The rotation to Earth-fixed uses GMST (IAU-1982). The engine's two-body path uses a fuller
// EME2000→ECEF transform, so a ground-track point here can differ from the engine's internal frame
// by a small fraction of a degree over a day — immaterial for a globe, and the contact intervals
// (not this track) remain authoritative. TLE orbits are not sampled client-side (no SGP4 here);
// `sampleTwoBodyOrbit` returns null for anything but a circular TWO_BODY_V1 orbit.

import type { OrbitSpecDTO, TwoBodyElementsDTO } from '../../shared/api/types'
import type { Ecef } from './geo'

export interface OrbitSample {
  /** ISO-8601 UTC instant of the sample. */
  t: string
  /** Earth-fixed position, metres. */
  ecef: Ecef
}

const DEG = Math.PI / 180

/** Julian Date (UTC) from milliseconds since the Unix epoch. */
function julianDate(unixMs: number): number {
  return unixMs / 86_400_000 + 2_440_587.5
}

/** Greenwich Mean Sidereal Time (radians), IAU-1982 series, UT1≈UTC (display precision). */
export function gmstRad(unixMs: number): number {
  const t = (julianDate(unixMs) - 2_451_545.0) / 36_525.0
  const seconds =
    67_310.54841 +
    (876_600 * 3_600 + 8_640_184.812866) * t +
    0.093104 * t * t -
    6.2e-6 * t * t * t
  let frac = (seconds % 86_400) / 86_400
  if (frac < 0) frac += 1
  return frac * 2 * Math.PI
}

/** One Earth-fixed position for a circular two-body orbit at `unixMs`. Exported for unit tests. */
export function twoBodyEcefAt(el: TwoBodyElementsDTO, epochMs: number, unixMs: number): Ecef {
  const a = el.semi_major_axis_mm / 1_000 // metres
  const mu = el.mu_m3_per_s2
  const i = (el.inclination_udeg / 1_000_000) * DEG
  const raan = (el.raan_udeg / 1_000_000) * DEG
  const argp = (el.argument_of_perigee_udeg / 1_000_000) * DEG
  const nu0 = (el.true_anomaly_udeg / 1_000_000) * DEG

  const n = Math.sqrt(mu / (a * a * a)) // mean motion, rad/s (== true rate for a circle)
  const dtSec = (unixMs - epochMs) / 1_000
  const u = argp + nu0 + n * dtSec // argument of latitude

  const cu = Math.cos(u)
  const su = Math.sin(u)
  const cO = Math.cos(raan)
  const sO = Math.sin(raan)
  const ci = Math.cos(i)
  const si = Math.sin(i)

  // Inertial (ECI) position on the circle of radius a.
  const xe = a * (cO * cu - sO * su * ci)
  const ye = a * (sO * cu + cO * su * ci)
  const ze = a * (su * si)

  // ECI → ECEF by Earth rotation θ = GMST.
  const th = gmstRad(unixMs)
  const ct = Math.cos(th)
  const st = Math.sin(th)
  return {
    x: ct * xe + st * ye,
    y: -st * xe + ct * ye,
    z: ze,
  }
}

/** Orbital period (seconds) of a circular two-body orbit. */
export function orbitalPeriodSec(el: TwoBodyElementsDTO): number {
  const a = el.semi_major_axis_mm / 1_000
  return 2 * Math.PI * Math.sqrt((a * a * a) / el.mu_m3_per_s2)
}

export interface SampleOptions {
  /** Sampling step in seconds (default 30). */
  stepSeconds?: number
  /** Hard cap on sample count, so an accidentally huge window can't lock the tab (default 5000). */
  maxSamples?: number
}

/**
 * Sample a circular TWO_BODY_V1 orbit over `[windowStartIso, windowEndIso)` into Earth-fixed points.
 * Returns null when the orbit is absent, a TLE, or not TWO_BODY_V1 (no client-side SGP4) — the view
 * then shows the stations and contact list without a drawn track.
 */
export function sampleTwoBodyOrbit(
  orbit: OrbitSpecDTO | null | undefined,
  windowStartIso: string,
  windowEndIso: string,
  options: SampleOptions = {},
): OrbitSample[] | null {
  if (!orbit || orbit.kind !== 'TWO_BODY_V1' || !orbit.two_body) return null
  const el = orbit.two_body
  const epochMs = Date.parse(el.epoch)
  const startMs = Date.parse(windowStartIso)
  const endMs = Date.parse(windowEndIso)
  if (!Number.isFinite(epochMs) || !Number.isFinite(startMs) || !Number.isFinite(endMs)) return null
  if (endMs <= startMs) return null

  const step = Math.max(1, options.stepSeconds ?? 30) * 1_000
  const maxSamples = Math.max(2, options.maxSamples ?? 5_000)
  const spanMs = endMs - startMs
  const count = Math.min(maxSamples, Math.floor(spanMs / step) + 1)
  const effectiveStep = count > 1 ? spanMs / (count - 1) : spanMs

  const samples: OrbitSample[] = []
  for (let k = 0; k < count; k++) {
    const ms = startMs + Math.round(k * effectiveStep)
    samples.push({ t: new Date(ms).toISOString(), ecef: twoBodyEcefAt(el, epochMs, ms) })
  }
  return samples
}
