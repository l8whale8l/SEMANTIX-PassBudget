import { describe, expect, it } from 'vitest'
import type { FixtureContent, RunResult } from '../../shared/api/types'
import orbContent from '../scenario/presets/PB-GOLDEN-ORB-01.json'
import { activeContactsAt, buildGlobeModel, satelliteEcefAt } from './model'
import type { OrbitSample } from './orbit'

const CONTENT = orbContent as unknown as FixtureContent
const W_START = '2026-09-03T00:00:00Z'
const W_END = '2026-09-04T00:00:00Z'

function resultWith(
  accesses: { key: string; station: string; aos: string; los: string; maxEl?: number }[],
  scheduled: { station: string; start: string; end: string }[] = [],
): RunResult {
  return {
    geometric_accesses: accesses.map((a) => ({
      stable_key: a.key,
      station_key: a.station,
      true_aos: a.aos,
      true_los: a.los,
      calculation_status: 'COMPUTED',
      decision_grade: 'CONCEPT_ONLY',
      maximum_elevation_udeg: a.maxEl ?? null,
      maximum_elevation_at: null,
      clipped_start: false,
      clipped_end: false,
    })),
    scheduled_sessions: scheduled.map((s, i) => ({
      stable_key: `sched/${i}`,
      candidate_stable_key: `cand/${i}`,
      station_key: s.station,
      selection_ordinal: i,
      usable_start: s.start,
      usable_end: s.end,
      capacity_bytes: 1000,
      calculation_status: 'COMPUTED',
      decision_grade: 'CONCEPT_ONLY',
      reason_codes: [],
    })),
  } as unknown as RunResult
}

describe('buildGlobeModel', () => {
  it('maps the preset stations to geodetic markers with Earth-fixed positions', () => {
    const model = buildGlobeModel(CONTENT, resultWith([]), W_START, W_END)
    const byKey = Object.fromEntries(model.stations.map((s) => [s.key, s]))
    expect(model.stations).toHaveLength(2)
    expect(byKey['SYN-GS-MIDLAT'].latitudeDeg).toBeCloseTo(37.6, 6)
    expect(byKey['SYN-GS-MIDLAT'].longitudeDeg).toBeCloseTo(127, 6)
    expect(byKey['SYN-GS-EQUATOR'].latitudeDeg).toBeCloseTo(0, 6)
    // ECEF magnitude ≈ Earth radius + height.
    expect(Math.hypot(byKey['SYN-GS-EQUATOR'].ecef.x, byKey['SYN-GS-EQUATOR'].ecef.y)).toBeGreaterThan(
      6_370_000,
    )
    // The preset orbit is TWO_BODY_V1, so a track is sampled.
    expect(model.track).not.toBeNull()
    expect(model.track!.length).toBeGreaterThan(10)
  })

  it('carries each geometric contact through with a scheduled flag from overlapping downlinks', () => {
    const model = buildGlobeModel(
      CONTENT,
      resultWith(
        [
          { key: 'g/1', station: 'SYN-GS-MIDLAT', aos: '2026-09-03T02:00:00Z', los: '2026-09-03T02:10:00Z', maxEl: 45_000_000 },
          { key: 'g/2', station: 'SYN-GS-EQUATOR', aos: '2026-09-03T05:00:00Z', los: '2026-09-03T05:08:00Z' },
        ],
        // A scheduled downlink that overlaps only the first contact.
        [{ station: 'SYN-GS-MIDLAT', start: '2026-09-03T02:03:00Z', end: '2026-09-03T02:09:00Z' }],
      ),
      W_START,
      W_END,
    )
    const byKey = Object.fromEntries(model.contacts.map((c) => [c.stableKey, c]))
    expect(byKey['g/1'].scheduled).toBe(true)
    expect(byKey['g/1'].maximumElevationDeg).toBeCloseTo(45, 6)
    expect(byKey['g/2'].scheduled).toBe(false)
    expect(byKey['g/2'].maximumElevationDeg).toBeNull()
  })

  it('reports a contact whose station is no longer in the scenario instead of dropping it silently', () => {
    const model = buildGlobeModel(
      CONTENT,
      resultWith([{ key: 'g/x', station: 'GS-DELETED', aos: '2026-09-03T01:00:00Z', los: '2026-09-03T01:05:00Z' }]),
      W_START,
      W_END,
    )
    expect(model.missingStationKeys).toEqual(['GS-DELETED'])
  })
})

describe('activeContactsAt', () => {
  const model = buildGlobeModel(
    CONTENT,
    resultWith([
      { key: 'g/1', station: 'SYN-GS-MIDLAT', aos: '2026-09-03T02:00:00Z', los: '2026-09-03T02:10:00Z' },
    ]),
    W_START,
    W_END,
  )

  it('includes a contact during its window and excludes it outside (half-open)', () => {
    expect(activeContactsAt(model.contacts, Date.parse('2026-09-03T02:05:00Z')).map((c) => c.stableKey)).toEqual([
      'g/1',
    ])
    expect(activeContactsAt(model.contacts, Date.parse('2026-09-03T02:10:00Z'))).toHaveLength(0) // los excluded
    expect(activeContactsAt(model.contacts, Date.parse('2026-09-03T01:59:00Z'))).toHaveLength(0)
  })
})

describe('satelliteEcefAt', () => {
  const track: OrbitSample[] = [
    { t: '2026-09-03T00:00:00Z', ecef: { x: 0, y: 0, z: 0 } },
    { t: '2026-09-03T00:01:00Z', ecef: { x: 60, y: 120, z: -60 } },
  ]

  it('linearly interpolates between samples', () => {
    const mid = satelliteEcefAt(track, Date.parse('2026-09-03T00:00:30Z'))!
    expect(mid.x).toBeCloseTo(30, 6)
    expect(mid.y).toBeCloseTo(60, 6)
    expect(mid.z).toBeCloseTo(-30, 6)
  })

  it('clamps to the endpoints outside the track and returns null for no track', () => {
    expect(satelliteEcefAt(track, Date.parse('2026-09-02T00:00:00Z'))).toEqual({ x: 0, y: 0, z: 0 })
    expect(satelliteEcefAt(track, Date.parse('2026-09-05T00:00:00Z'))).toEqual({ x: 60, y: 120, z: -60 })
    expect(satelliteEcefAt(null, 0)).toBeNull()
  })
})
