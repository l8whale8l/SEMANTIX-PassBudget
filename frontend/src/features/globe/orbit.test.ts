import { describe, expect, it } from 'vitest'
import type { OrbitSpecDTO, TwoBodyElementsDTO } from '../../shared/api/types'
import { ecefToGeodetic } from './geo'
import { orbitalPeriodSec, sampleTwoBodyOrbit, twoBodyEcefAt } from './orbit'

// The golden preset's circular sun-synchronous orbit (~700 km, i=98°).
const EL: TwoBodyElementsDTO = {
  epoch: '2026-09-03T00:00:00.000000Z',
  semi_major_axis_mm: 7_078_137_000,
  eccentricity_ppb: 0,
  inclination_udeg: 98_000_000,
  raan_udeg: 90_000_000,
  argument_of_perigee_udeg: 0,
  true_anomaly_udeg: 0,
  mu_m3_per_s2: 398_600_441_500_000,
}
const ORBIT: OrbitSpecDTO = { kind: 'TWO_BODY_V1', two_body: EL }
const SMA_M = 7_078_137

describe('orbitalPeriodSec', () => {
  it('matches Kepler for a ~700 km LEO (≈98.8 min)', () => {
    // Independent: T = 2π√(a³/µ) with a=7078.137 km ⇒ ~5926 s.
    expect(orbitalPeriodSec(EL)).toBeGreaterThan(5900)
    expect(orbitalPeriodSec(EL)).toBeLessThan(5960)
  })
})

describe('twoBodyEcefAt', () => {
  it('keeps the circular radius equal to the semi-major axis at every time', () => {
    const epochMs = Date.parse(EL.epoch)
    for (const dt of [0, 1000, 2963_000, 5926_000, 40_000_000]) {
      const p = twoBodyEcefAt(EL, epochMs, epochMs + dt)
      const r = Math.hypot(p.x, p.y, p.z)
      expect(r).toBeCloseTo(SMA_M, 1) // metres — a circle stays at radius a
    }
  })

  it('rotating the Earth frame preserves the position magnitude (ECI→ECEF is a rotation)', () => {
    const epochMs = Date.parse(EL.epoch)
    const a = twoBodyEcefAt(EL, epochMs, epochMs)
    const b = twoBodyEcefAt(EL, epochMs, epochMs + 3600_000)
    expect(Math.hypot(a.x, a.y, a.z)).toBeCloseTo(Math.hypot(b.x, b.y, b.z), 1)
  })
})

describe('sampleTwoBodyOrbit', () => {
  it('returns null for a TLE or a missing orbit (no client-side SGP4)', () => {
    expect(sampleTwoBodyOrbit(null, EL.epoch, '2026-09-04T00:00:00Z')).toBeNull()
    expect(
      sampleTwoBodyOrbit(
        { kind: 'GP_TLE', tle: { line_1: 'x', line_2: 'y' } },
        EL.epoch,
        '2026-09-04T00:00:00Z',
      ),
    ).toBeNull()
  })

  it('samples the window and honours the sample cap', () => {
    const samples = sampleTwoBodyOrbit(ORBIT, '2026-09-03T00:00:00Z', '2026-09-04T00:00:00Z', {
      stepSeconds: 60,
      maxSamples: 5000,
    })!
    expect(samples).not.toBeNull()
    // 24 h / 60 s = 1440 steps ⇒ 1441 inclusive samples.
    expect(samples.length).toBe(1441)
    expect(samples[0].t).toBe('2026-09-03T00:00:00.000Z')
    expect(Date.parse(samples[samples.length - 1].t)).toBe(Date.parse('2026-09-04T00:00:00Z'))
  })

  it('caps the sample count for a coarse cap', () => {
    const samples = sampleTwoBodyOrbit(ORBIT, '2026-09-03T00:00:00Z', '2026-09-04T00:00:00Z', {
      stepSeconds: 1,
      maxSamples: 100,
    })!
    expect(samples.length).toBe(100)
  })

  it('produces a ground track whose latitude amplitude matches the inclination (180−i = 82°)', () => {
    const samples = sampleTwoBodyOrbit(ORBIT, '2026-09-03T00:00:00Z', '2026-09-04T00:00:00Z', {
      stepSeconds: 30,
    })!
    const lats = samples.map((s) => ecefToGeodetic(s.ecef).latitudeDeg)
    const maxAbs = Math.max(...lats.map(Math.abs))
    // A 98° inclination confines the sub-satellite latitude to ±82°.
    expect(maxAbs).toBeGreaterThan(80)
    expect(maxAbs).toBeLessThan(83)
    expect(Math.min(...lats)).toBeLessThan(-80)
  })

  it('keeps every sample near the 700 km orbital altitude', () => {
    const samples = sampleTwoBodyOrbit(ORBIT, '2026-09-03T00:00:00Z', '2026-09-04T00:00:00Z', {
      stepSeconds: 120,
    })!
    // The orbit is a sphere of radius a about Earth's centre; height ABOVE the WGS-84 ellipsoid is
    // ~700 km at the equator and rises to ~720 km near the poles (where the ellipsoid surface sits
    // ~21 km lower). This spread is physical, not error.
    for (const s of samples) {
      const h = ecefToGeodetic(s.ecef).heightM
      expect(h).toBeGreaterThan(698_000)
      expect(h).toBeLessThan(721_000)
    }
  })
})
