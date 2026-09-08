// Per-scenario persistence of the UI-only field evidence marks (measured / provisional / assumption).
//
// Marks are display metadata only — they never touch the executable content, the request, or the
// hash — so they cannot ride along in the saved server scenario. They live in localStorage instead,
// keyed by the scenario's identity so reopening the same scenario restores which values were marked.
// Every access is guarded so a blocked/empty/corrupt store degrades to "no marks".

import type { EvidenceMark } from '../../shared/ui/evidence'

const KEY = 'passbudget.evidenceMarks.v1'

/** All scenarios' marks: { [scenarioKey]: { [fieldKey]: mark } }. */
type Store = Record<string, Record<string, EvidenceMark>>

const VALID: ReadonlySet<string> = new Set(['unset', 'assumption', 'provisional', 'measured'])

function readStore(): Store {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    return parsed as Store
  } catch {
    return {}
  }
}

function writeStore(store: Store): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(store))
  } catch {
    // Non-fatal: marks are a convenience; losing them never affects the calculation.
  }
}

/** Load one scenario's marks, dropping any malformed entries. */
export function loadEvidenceMarks(scenarioKey: string): Record<string, EvidenceMark> {
  const bucket = readStore()[scenarioKey]
  if (!bucket || typeof bucket !== 'object') return {}
  const out: Record<string, EvidenceMark> = {}
  for (const [field, mark] of Object.entries(bucket)) {
    if (typeof field === 'string' && typeof mark === 'string' && VALID.has(mark)) {
      out[field] = mark as EvidenceMark
    }
  }
  return out
}

/** Persist one scenario's marks (fields marked 'unset' are dropped to keep the store small). */
export function saveEvidenceMarks(scenarioKey: string, marks: Record<string, EvidenceMark>): void {
  const store = readStore()
  const bucket: Record<string, EvidenceMark> = {}
  for (const [field, mark] of Object.entries(marks)) {
    if (mark && mark !== 'unset') bucket[field] = mark
  }
  if (Object.keys(bucket).length === 0) delete store[scenarioKey]
  else store[scenarioKey] = bucket
  writeStore(store)
}
