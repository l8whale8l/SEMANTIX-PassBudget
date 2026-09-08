import { describe, expect, it } from 'vitest'
import { ORB_PRESET } from './presets'
import {
  buildFixtureContent,
  buildRunRequest,
  createPayloadForm,
  DraftValidationError,
  draftFromContent,
  draftFromPreset,
  isPristine,
  rebaseSavedDraft,
  saveScopeWarnings,
} from './draft'

function newOutput(overrides = {}) {
  return createPayloadForm({
    stableKey: 'OUTPUT-1',
    displayName: 'pasted-output',
    logicalSizeBytes: 12345,
    readyAt: '2026-09-03T00:00:00Z',
    queueSequence: 9,
    sizeSource: 'UTF-8 붙여넣기',
    ...overrides,
  })
}

describe('scenario draft round-trip (FE-02)', () => {
  it('serializes an unedited preset byte-identically to the seed', () => {
    const draft = draftFromPreset(ORB_PRESET)
    expect(isPristine(draft)).toBe(true)
    expect(buildFixtureContent(draft)).toEqual(ORB_PRESET.content)
  })

  it('sends an unedited preset by fixture id, not as a snapshot (FE-03)', () => {
    const draft = draftFromPreset(ORB_PRESET)
    expect(buildRunRequest(draft)).toEqual({ fixture: 'PB-GOLDEN-ORB-01' })
  })

  it('preserves hidden advanced capacity fields through the round-trip', () => {
    const draft = draftFromPreset(ORB_PRESET)
    const built = buildFixtureContent(draft)
    expect(built.stations[0].capacity.accounted_effects).toEqual([
      'CODING',
      'PROTOCOL_OVERHEAD',
      'RESIDUAL_LOSS',
    ])
    expect(built.stations[0].capacity.evidence_state).toBe('PROXY')
    expect(built.stations[0].capacity.measurement_point).toBe(
      'SYNTHETIC_SPACECRAFT_APPLICATION_EGRESS',
    )
  })

  it('does not carry the UI-only scenario name into the DTO', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.scenarioName = 'my edited label'
    const built = buildFixtureContent(draft)
    expect(JSON.stringify(built)).not.toContain('my edited label')
  })
})

describe('editing produces a snapshot request (FE-04)', () => {
  it('emits a snapshot with the changed station coordinate', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.stations[0].latitudeUdeg = '38000000'
    const req = buildRunRequest(draft)
    expect('snapshot' in req).toBe(true)
    if ('snapshot' in req) {
      expect(req.snapshot.stations[0].site?.latitude_udeg).toBe(38_000_000)
    }
    expect(isPristine(draft)).toBe(false)
  })

  it('excludes an inactive station from the request but keeps it in the draft', () => {
    const draft = draftFromPreset(ORB_PRESET)
    expect(draft.stations).toHaveLength(2)
    draft.stations[1].active = false
    const built = buildFixtureContent(draft)
    expect(built.stations).toHaveLength(1)
    expect(built.stations[0].stable_key).toBe('SYN-GS-MIDLAT')
    // The inactive station is still present in the editable draft.
    expect(draft.stations).toHaveLength(2)
  })
})

describe('draft validation (FE-07, FE-27)', () => {
  it('rejects when every station is inactive', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.stations.forEach((s) => (s.active = false))
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)
  })

  it('rejects a non-integer coordinate rather than truncating it', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.stations[0].latitudeUdeg = '37.6'
    expect(() => buildFixtureContent(draft)).toThrow()
  })

  it('rejects an out-of-safe-range integer', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.stations[0].minimumElevationUdeg = '9007199254740993'
    expect(() => buildFixtureContent(draft)).toThrow()
  })

  it('rejects duplicate active station stable keys (correction 3)', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.stations[1].stableKey = draft.stations[0].stableKey
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)
  })
})

describe('analysis mode switch (correction 1)', () => {
  it('QUEUE_AWARE keeps payloads and policy from the seed', () => {
    const built = buildFixtureContent(draftFromPreset(ORB_PRESET))
    expect(built.analysis_mode).toBe('QUEUE_AWARE')
    expect((built.payloads ?? []).length).toBe(3)
    expect(built.policy_revision_id).toBeTruthy()
  })

  it('NETWORK_ONLY strips payloads, policy and storage the domain forbids there', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.analysisMode = 'NETWORK_ONLY'
    const built = buildFixtureContent(draft)
    expect(built.analysis_mode).toBe('NETWORK_ONLY')
    expect(built.payloads).toEqual([])
    expect('policy_revision_id' in built).toBe(false)
    expect('storage' in built).toBe(false)
  })

  it('preserves the payload/policy draft so a round-trip back to QUEUE_AWARE restores them', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.analysisMode = 'NETWORK_ONLY'
    buildFixtureContent(draft) // serialize once in NETWORK_ONLY
    draft.analysisMode = 'QUEUE_AWARE'
    const restored = buildFixtureContent(draft)
    expect((restored.payloads ?? []).length).toBe(3)
    expect(restored.policy_revision_id).toBeTruthy()
  })

  it('never sends BOUNDED_APPROXIMATE in NETWORK_ONLY even if the QUEUE_AWARE preference was set', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.executionStrategy = 'BOUNDED_APPROXIMATE'
    draft.analysisMode = 'NETWORK_ONLY'
    const built = buildFixtureContent(draft)
    // Effective strategy is EXACT_GLOBAL there; the seed omits the field, so it stays omitted.
    expect(built.execution_strategy).toBeUndefined()
  })

  it('sends the chosen strategy in QUEUE_AWARE', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.executionStrategy = 'BOUNDED_APPROXIMATE'
    const built = buildFixtureContent(draft)
    expect(built.execution_strategy).toBe('BOUNDED_APPROXIMATE')
  })

  it('keeps BOUNDED_APPROXIMATE when a saved approximate scenario is reloaded (omission bug)', () => {
    // A loaded scenario's baseContent already carries the non-default strategy. Omitting it would
    // silently flip the re-run to EXACT (the server default). It must stay BOUNDED_APPROXIMATE.
    const approxContent = JSON.parse(JSON.stringify(ORB_PRESET.content))
    approxContent.execution_strategy = 'BOUNDED_APPROXIMATE'
    const draft = draftFromContent(approxContent, { scenarioId: 's1', name: 'approx' })
    expect(draft.executionStrategy).toBe('BOUNDED_APPROXIMATE')
    expect(buildFixtureContent(draft).execution_strategy).toBe('BOUNDED_APPROXIMATE')
    // buildRunRequest must send it as a snapshot carrying the strategy (never bare fixture id).
    const req = buildRunRequest(draft)
    expect('snapshot' in req && req.snapshot.execution_strategy).toBe('BOUNDED_APPROXIMATE')
  })
})

describe('model-output cart (F2)', () => {
  it('round-trips the seed payloads unchanged (pristine stays pristine)', () => {
    expect(isPristine(draftFromPreset(ORB_PRESET))).toBe(true)
  })

  it('adds a new output as a snapshot request with a fresh key and measured size', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.payloads = [...draft.payloads, newOutput({ logicalSizeBytes: 4242 })]
    const req = buildRunRequest(draft)
    expect('snapshot' in req).toBe(true)
    if ('snapshot' in req) {
      expect(req.snapshot.payloads).toHaveLength(4)
      const added = req.snapshot.payloads!.find((p) => p.stable_key === 'OUTPUT-1')
      expect(added?.logical_size_bytes).toBe(4242)
      expect(added?.storage_size_bytes).toBe(4242) // defaults to logical
      expect(added?.segmentation).toBe('ATOMIC_OBJECT')
      expect(added?.resume_supported).toBe(false)
      expect('chunk_size_bytes' in (added as object)).toBe(false)
    }
  })

  it('enforces FIXED_CHUNK => positive chunk + resume, ATOMIC => neither (FE-14)', () => {
    const draft = draftFromPreset(ORB_PRESET)
    const p = newOutput()
    draft.payloads = [...draft.payloads, p]

    // ATOMIC ignores any stale chunk/resume from the form.
    p.segmentation = 'ATOMIC_OBJECT'
    p.chunkSizeBytes = '1000000'
    p.resumeSupported = true
    let built = buildFixtureContent(draft)
    let added = built.payloads!.find((x) => x.stable_key === 'OUTPUT-1')!
    expect(added.resume_supported).toBe(false)
    expect('chunk_size_bytes' in added).toBe(false)

    // FIXED_CHUNK requires a positive chunk and forces resume on.
    p.segmentation = 'FIXED_CHUNK'
    p.chunkSizeBytes = '500000'
    built = buildFixtureContent(draft)
    added = built.payloads!.find((x) => x.stable_key === 'OUTPUT-1')!
    expect(added.chunk_size_bytes).toBe(500_000)
    expect(added.resume_supported).toBe(true)

    // A non-positive chunk is rejected.
    p.chunkSizeBytes = '0'
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)
  })

  it('rejects a non-positive output size', () => {
    const draft = draftFromPreset(ORB_PRESET)
    const p = newOutput()
    p.logicalSizeBytes = '0'
    draft.payloads = [...draft.payloads, p]
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)
  })

  it('rejects a QUEUE_AWARE run with an empty cart, guiding to add or switch mode', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.payloads = []
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)
  })

  it('keeps the cart out of a NETWORK_ONLY request but preserves the draft', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.payloads = [...draft.payloads, newOutput()]
    draft.analysisMode = 'NETWORK_ONLY'
    const built = buildFixtureContent(draft)
    expect(built.payloads).toEqual([])
    expect(draft.payloads).toHaveLength(4) // draft untouched
  })

  it('rejects duplicate output stable keys', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.payloads = [...draft.payloads, newOutput({ stableKey: draft.payloads[0].stableKey })]
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)
  })

  it('bounds mission_priority to 0..100 and rejects a negative queue sequence (defect 2)', () => {
    const draft = draftFromPreset(ORB_PRESET)
    const p = newOutput()
    draft.payloads = [...draft.payloads, p]

    p.missionPriority = '200'
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)

    p.missionPriority = '-1'
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)

    p.missionPriority = '50'
    p.queueSequence = '-3'
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)

    p.queueSequence = '5'
    expect(() => buildFixtureContent(draft)).not.toThrow()
  })

  it('serializes dependencies from the draft and preserves them intact (defect 2)', () => {
    const base = JSON.parse(JSON.stringify(ORB_PRESET.content))
    base.dependencies = [
      { predecessor_key: 'WILDFIRE-DETECT', successor_key: 'SHIP-DETECT', kind: 'SEND_AFTER' },
    ]
    const draft = draftFromPreset({ ...ORB_PRESET, content: base })
    expect(draft.dependencies).toHaveLength(1)
    const built = buildFixtureContent(draft)
    expect(built.dependencies).toEqual([
      { predecessor_key: 'WILDFIRE-DETECT', successor_key: 'SHIP-DETECT', kind: 'SEND_AFTER' },
    ])
  })

  it('THROWS (not silently drops) when a dependency references a missing payload (defect 2)', () => {
    const base = JSON.parse(JSON.stringify(ORB_PRESET.content))
    base.dependencies = [
      { predecessor_key: 'WILDFIRE-DETECT', successor_key: 'SHIP-DETECT', kind: 'SEND_AFTER' },
    ]
    const draft = draftFromPreset({ ...ORB_PRESET, content: base })
    // Force an inconsistent graph (the UI blocks this; the build is the safety net).
    draft.payloads = draft.payloads.filter((p) => p.stableKey !== 'SHIP-DETECT')
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)
  })

  it('THROWS when a synthetic delivery event references a missing payload', () => {
    const base = JSON.parse(JSON.stringify(ORB_PRESET.content))
    base.synthetic_delivery_events = [
      { payload_key: 'WILDFIRE-DETECT', acknowledged_at: '2026-09-03T04:00:00Z' },
    ]
    const draft = draftFromPreset({ ...ORB_PRESET, content: base })
    draft.payloads = draft.payloads.filter((p) => p.stableKey !== 'WILDFIRE-DETECT')
    expect(() => buildFixtureContent(draft)).toThrow(DraftValidationError)
  })

  it('excludes payloads AND dependencies in NETWORK_ONLY without validating them (defect 1)', () => {
    const base = JSON.parse(JSON.stringify(ORB_PRESET.content))
    base.dependencies = [
      { predecessor_key: 'WILDFIRE-DETECT', successor_key: 'SHIP-DETECT', kind: 'SEND_AFTER' },
    ]
    const draft = draftFromPreset({ ...ORB_PRESET, content: base })
    // A payload draft that would be INVALID in QUEUE_AWARE (missing chunk for FIXED_CHUNK)...
    draft.payloads[0].segmentation = 'FIXED_CHUNK'
    draft.payloads[0].chunkSizeBytes = '0'
    // ...must not block a NETWORK_ONLY run, because payloads are excluded before validation.
    draft.analysisMode = 'NETWORK_ONLY'
    const built = buildFixtureContent(draft)
    expect(built.payloads).toEqual([])
    expect('dependencies' in built).toBe(false)
  })

  it('rebaseSavedDraft keeps editing state (inactive stations, cart) while marking it saved (CLOSE-03)', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.stations[1].active = false // an inactive station draft
    const savedContent = buildFixtureContent(draft) // excludes the inactive station
    const rebased = rebaseSavedDraft(draft, savedContent, { scenarioId: 'sc-9', name: 'kept' })
    // The saved identity is set...
    expect(rebased.savedScenarioId).toBe('sc-9')
    expect(rebased.presetIsPublicFixture).toBe(false)
    // ...but the inactive station is NOT discarded from the working draft.
    expect(rebased.stations).toHaveLength(2)
    expect(rebased.stations[1].active).toBe(false)
    // Pristine holds (the executable content still excludes the inactive station).
    expect(isPristine(rebased)).toBe(true)
  })

  it('saveScopeWarnings surfaces editing state the executable save cannot persist (CLOSE-03)', () => {
    const clean = draftFromPreset(ORB_PRESET)
    expect(saveScopeWarnings(clean)).toEqual([])

    const withInactive = draftFromPreset(ORB_PRESET)
    withInactive.stations[1].active = false
    expect(saveScopeWarnings(withInactive).join(' ')).toMatch(/비활성 지상국/)

    const networkOnlyWithCart = draftFromPreset(ORB_PRESET)
    networkOnlyWithCart.analysisMode = 'NETWORK_ONLY'
    expect(saveScopeWarnings(networkOnlyWithCart).join(' ')).toMatch(/장바구니/)
  })

  it('rebuilds an editable draft from saved content and always runs it as a snapshot (F3 load)', () => {
    const content = JSON.parse(JSON.stringify(ORB_PRESET.content))
    const draft = draftFromContent(content, { scenarioId: 'sc-123', name: '내 시나리오' })
    expect(draft.savedScenarioId).toBe('sc-123')
    expect(draft.presetIsPublicFixture).toBe(false)
    // Fields are restored equal to the saved content.
    expect(buildFixtureContent(draft)).toEqual(content)
    // A loaded scenario never runs by fixture id (its id is not a packaged public fixture).
    const req = buildRunRequest(draft)
    expect('snapshot' in req).toBe(true)
  })

  it('never carries raw pasted content — only byte metadata — in the built payload', () => {
    const draft = draftFromPreset(ORB_PRESET)
    draft.payloads = [...draft.payloads, newOutput({ displayName: 'note', logicalSizeBytes: 42 })]
    const built = buildFixtureContent(draft)
    const added = built.payloads!.find((p) => p.stable_key === 'OUTPUT-1')!
    // The measured size is present; there is no free-text content field on the payload DTO.
    expect(added.logical_size_bytes).toBe(42)
    expect(Object.keys(added)).not.toContain('content')
    expect(Object.keys(added)).not.toContain('body')
    expect(Object.keys(added)).not.toContain('text')
  })
})
