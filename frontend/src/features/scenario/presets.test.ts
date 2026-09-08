import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { DEFAULT_PRESET, ORB_PRESET, PRESETS } from './presets'
import { buildRunRequest, draftFromPreset } from './draft'

// The frontend ships a bundled copy of the public ORB fixture because there is still no
// revision-content read API (FE-GAP-01 remains open). This test guards that the bundled copy stays
// semantically equal to the backend original, so the seed the user edits is the real fixture.
// This is a *structural* (parsed-object) equality check, not a byte-for-byte comparison.
// Default: resolve the backend fixture relative to this source file (works when the frontend runs
// in place inside the repo). When the toolchain runs from an isolated ASCII copy (see the frontend
// README's non-ASCII-path note), PB_BACKEND_FIXTURE points at the real backend fixture instead — a
// file read, which Node performs fine even on the non-ASCII repo path.
const backendFixturePath =
  process.env.PB_BACKEND_FIXTURE ??
  fileURLToPath(
    new URL('../../../../src/semantix_passbudget/fixtures/PB-GOLDEN-ORB-01.json', import.meta.url),
  )

describe('bundled ORB preset (correction 7)', () => {
  it('is semantically equal to the backend original fixture', () => {
    const backend = JSON.parse(readFileSync(backendFixturePath, 'utf-8'))
    expect(ORB_PRESET.content).toEqual(backend)
  })

  it('is the QUEUE_AWARE ORBIT_DERIVED fixture with no injected contacts and no real TLE', () => {
    expect(ORB_PRESET.fixtureId).toBe('PB-GOLDEN-ORB-01')
    expect(ORB_PRESET.content.contact_source).toBe('ORBIT_DERIVED')
    expect(ORB_PRESET.content.contacts).toEqual([])
    expect(ORB_PRESET.content.orbit?.kind).toBe('TWO_BODY_V1')
    expect(ORB_PRESET.content.orbit?.tle ?? null).toBeNull()
  })
})

describe('public preset boundary', () => {
  it('opens the public synthetic fixture by default', () => {
    expect(DEFAULT_PRESET).toBe(ORB_PRESET)
    expect(PRESETS).toEqual([ORB_PRESET])
    expect(DEFAULT_PRESET.isPublicFixture).toBe(true)
  })

  it('uses the fixture request while pristine and a snapshot after edits', () => {
    const draft = draftFromPreset(DEFAULT_PRESET)
    expect(buildRunRequest(draft)).toEqual({ fixture: 'PB-GOLDEN-ORB-01' })

    draft.stations[0].active = false
    expect(buildRunRequest(draft)).toHaveProperty('snapshot')
  })
})
