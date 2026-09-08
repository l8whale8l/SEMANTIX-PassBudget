// A UI-only per-field tag marking whether an input value is measured, provisional, or an assumption.
//
// This is purely a display/bookkeeping aid so the user can see at a glance how much of a scenario is
// real data vs. placeholder, and later replace only the assumptions when measured values arrive. It
// NEVER enters the executable content, the request, the hash, or the golden — the calculation is
// identical regardless of a value's mark. Marks are persisted per scenario in localStorage.

export type EvidenceMark = 'unset' | 'assumption' | 'provisional' | 'measured'

/** Click-cycle order: unmarked → 가정 → 잠정 → 실측 → back to unmarked. Marking an assumption (the
 *  usual first state of a placeholder value) is a single click. */
const ORDER: readonly EvidenceMark[] = ['unset', 'assumption', 'provisional', 'measured']

export function cycleEvidence(mark: EvidenceMark): EvidenceMark {
  const i = ORDER.indexOf(mark)
  return ORDER[(i + 1) % ORDER.length]
}

export interface EvidenceMeta {
  /** Short Korean label for tooltip/aria. */
  label: string
  /** The dot's colour-tone class suffix (green/amber/red/grey). */
  tone: 'ok' | 'warn' | 'danger' | 'muted'
}

export function evidenceMeta(mark: EvidenceMark): EvidenceMeta {
  switch (mark) {
    case 'measured':
      return { label: '실측값', tone: 'ok' }
    case 'provisional':
      return { label: '잠정·추정값', tone: 'warn' }
    case 'assumption':
      return { label: '가정값(실측 아님)', tone: 'danger' }
    default:
      return { label: '미지정', tone: 'muted' }
  }
}

// Field-name lists per panel (the suffix after the `orbit:` / `station:<key>:` prefix). Kept here so
// the legend's counts enumerate exactly the fields the forms render marks for.
export const ORBIT_TWO_BODY_FIELDS = [
  'epoch',
  'semiMajorAxisMm',
  'eccentricityPpb',
  'inclinationUdeg',
  'raanUdeg',
  'argumentOfPerigeeUdeg',
  'trueAnomalyUdeg',
  'muM3PerS2',
] as const
export const ORBIT_TLE_FIELDS = ['tleLine1', 'tleLine2'] as const
export const STATION_FIELDS = [
  'preferenceRank',
  'latitudeUdeg',
  'longitudeEastUdeg',
  'ellipsoidalHeightMm',
  'minimumElevationUdeg',
  'rate',
  'efficiency',
] as const

export type EvidenceCounts = Record<EvidenceMark, number>

/** Tally the marks across a set of field keys (unknown keys count as 'unset'). */
export function countMarks(get: (key: string) => EvidenceMark, keys: readonly string[]): EvidenceCounts {
  const counts: EvidenceCounts = { unset: 0, assumption: 0, provisional: 0, measured: 0 }
  for (const k of keys) counts[get(k)] += 1
  return counts
}

/**
 * The handle threaded into input forms so each field can read and cycle its own mark by a stable key.
 * `get` returns 'unset' for any unknown key. Field keys are plain strings owned by the caller
 * (e.g. `orbit:inclinationUdeg`, `station:<stableKey>:latitudeUdeg`).
 */
export interface EvidenceControl {
  get: (fieldKey: string) => EvidenceMark
  cycle: (fieldKey: string) => void
}
