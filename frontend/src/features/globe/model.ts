// Pure globe model (F5): turn a run's scenario geometry + backend result into the shapes the Cesium
// view draws. No Cesium, no WebGL, no network — unit-testable in jsdom. The satellite track is a
// display re-sample of the run's own orbit elements (see orbit.ts); every contact interval comes
// verbatim from the backend result. Nothing here alters a computed coordinate or the transfer
// budget.

import type { FixtureContent, GeometricAccess, RunResult, ScheduledSession } from '../../shared/api/types'
import { geodeticToEcef, mmToM, udegToDeg, type Ecef } from './geo'
import { sampleTwoBodyOrbit, type OrbitSample, type SampleOptions } from './orbit'

export interface GlobeStation {
  key: string
  latitudeDeg: number
  longitudeDeg: number
  heightM: number
  minimumElevationDeg: number
  ecef: Ecef
}

export interface GlobeContact {
  stableKey: string
  stationKey: string
  aosIso: string
  losIso: string
  aosMs: number
  losMs: number
  /** True when a scheduled downlink session for this station overlaps this geometric window. */
  scheduled: boolean
  maximumElevationDeg: number | null
}

export interface GlobeModel {
  stations: GlobeStation[]
  /** Sampled Earth-fixed satellite track, or null when the orbit can't be sampled client-side. */
  track: OrbitSample[] | null
  contacts: GlobeContact[]
  windowStartMs: number
  windowEndMs: number
  /** Stations named by a contact but missing geometry (e.g. edited away) — surfaced, not hidden. */
  missingStationKeys: string[]
  /** UI-only satellite display name for the globe marker label (defaults to "위성"). */
  satelliteName?: string
}

function stationsFromContent(content: FixtureContent): GlobeStation[] {
  const stations: GlobeStation[] = []
  for (const s of content.stations) {
    if (!s.site) continue // synthetic scenarios have no geodetic site — nothing to place
    const latitudeDeg = udegToDeg(s.site.latitude_udeg)
    const longitudeDeg = udegToDeg(s.site.longitude_east_udeg)
    const heightM = mmToM(s.site.ellipsoidal_height_mm)
    stations.push({
      key: s.stable_key,
      latitudeDeg,
      longitudeDeg,
      heightM,
      minimumElevationDeg: udegToDeg(s.site.minimum_elevation_udeg),
      ecef: geodeticToEcef({ latitudeDeg, longitudeDeg, heightM }),
    })
  }
  return stations
}

function scheduledOverlaps(
  scheduled: ScheduledSession[],
  stationKey: string,
  aosMs: number,
  losMs: number,
): boolean {
  return scheduled.some((s) => {
    if (s.station_key !== stationKey) return false
    const start = Date.parse(s.usable_start)
    const end = Date.parse(s.usable_end)
    if (!Number.isFinite(start) || !Number.isFinite(end)) return false
    return start < losMs && end > aosMs // half-open interval overlap
  })
}

function contactsFromResult(result: RunResult): GlobeContact[] {
  const accesses = (result.geometric_accesses ?? []) as GeometricAccess[]
  const scheduled = (result.scheduled_sessions ?? []) as ScheduledSession[]
  const contacts: GlobeContact[] = []
  for (const a of accesses) {
    const aosMs = Date.parse(a.true_aos)
    const losMs = Date.parse(a.true_los)
    if (!Number.isFinite(aosMs) || !Number.isFinite(losMs)) continue
    contacts.push({
      stableKey: a.stable_key,
      stationKey: a.station_key,
      aosIso: a.true_aos,
      losIso: a.true_los,
      aosMs,
      losMs,
      scheduled: scheduledOverlaps(scheduled, a.station_key, aosMs, losMs),
      maximumElevationDeg: a.maximum_elevation_udeg == null ? null : udegToDeg(a.maximum_elevation_udeg),
    })
  }
  return contacts
}

/**
 * Build the globe model from the run's own scenario body (`content`, source of station geometry and
 * the orbit elements) and the backend `result` (source of every contact window). `windowStartIso` /
 * `windowEndIso` bound the drawn track — pass the run's analysis window.
 */
export function buildGlobeModel(
  content: FixtureContent,
  result: RunResult,
  windowStartIso: string,
  windowEndIso: string,
  sampleOptions?: SampleOptions,
): GlobeModel {
  const stations = stationsFromContent(content)
  const contacts = contactsFromResult(result)
  const track = sampleTwoBodyOrbit(content.orbit, windowStartIso, windowEndIso, sampleOptions)

  const stationKeys = new Set(stations.map((s) => s.key))
  const missingStationKeys = [
    ...new Set(contacts.map((c) => c.stationKey).filter((k) => !stationKeys.has(k))),
  ]

  return {
    stations,
    track,
    contacts,
    windowStartMs: Date.parse(windowStartIso),
    windowEndMs: Date.parse(windowEndIso),
    missingStationKeys,
  }
}

/**
 * A pre-run preview model: ground-station markers from the current draft only. No satellite track and
 * no contacts, so nothing uncomputed is shown as if it were a real result (the orbit and contact
 * windows appear only after a run). The window bounds the (empty) clock.
 */
export function previewGlobeModel(
  content: FixtureContent,
  windowStartIso: string,
  windowEndIso: string,
): GlobeModel {
  return {
    stations: stationsFromContent(content),
    track: null,
    contacts: [],
    windowStartMs: Date.parse(windowStartIso),
    windowEndMs: Date.parse(windowEndIso),
    missingStationKeys: [],
  }
}

/** Contacts active at instant `tMs` (half-open `[aos, los)`) — drives which connection lines glow. */
export function activeContactsAt(contacts: GlobeContact[], tMs: number): GlobeContact[] {
  return contacts.filter((c) => c.aosMs <= tMs && tMs < c.losMs)
}

/**
 * Earth-fixed satellite position at `tMs`, linearly interpolated between track samples. Returns null
 * when there is no track or `tMs` is outside its span. Interpolation is for the moving marker /
 * connection-line endpoint only; it is not a computed result.
 */
export function satelliteEcefAt(track: OrbitSample[] | null, tMs: number): Ecef | null {
  if (!track || track.length === 0) return null
  const firstMs = Date.parse(track[0].t)
  const lastMs = Date.parse(track[track.length - 1].t)
  if (tMs <= firstMs) return track[0].ecef
  if (tMs >= lastMs) return track[track.length - 1].ecef
  // Binary search for the segment containing tMs.
  let lo = 0
  let hi = track.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (Date.parse(track[mid].t) <= tMs) lo = mid
    else hi = mid
  }
  const aMs = Date.parse(track[lo].t)
  const bMs = Date.parse(track[hi].t)
  const f = bMs === aMs ? 0 : (tMs - aMs) / (bMs - aMs)
  const a = track[lo].ecef
  const b = track[hi].ecef
  return {
    x: a.x + (b.x - a.x) * f,
    y: a.y + (b.y - a.y) * f,
    z: a.z + (b.z - a.z) * f,
  }
}
