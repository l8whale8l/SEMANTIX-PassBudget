// The scenario draft: editable form state kept strictly separate from the executable DTO.
//
// Design rules from FRONTEND_IMPLEMENTATION_SPEC §6-7:
//   * The whole seed fixture is retained as `baseContent` and only edited leaves are overwritten,
//     so hidden advanced fields (storage, dependencies, evidence, accounted_effects, payload
//     details) survive a form round-trip untouched (FE-02).
//   * UI-only concepts — a friendly scenario name and per-station active flags — never enter the
//     strict FixtureDTO. Inactive stations are dropped from the request but preserved in the draft.
//   * Numbers are edited as strings and converted exactly on build; a non-integer or out-of-safe-
//     range value is rejected, never silently rounded (FE-27).

import type {
  FixtureContent,
  OrbitSpecDTO,
  PayloadDTO,
  StationDTO,
  TwoBodyElementsDTO,
} from '../../shared/api/types'
import { deepEqual, parseIntegerField } from '../../shared/format/json'
import { isUtcInstant } from '../../shared/format/time'
import { nextEditId } from '../../shared/ids'
import { ORB_PRESET, type PresetDescriptor } from './presets'

export type OrbitMode = 'TWO_BODY_V1' | 'GP_TLE'

export interface StationForm {
  /** Stable per-row edit id for React keys and unique new-key generation (not the domain key). */
  editId: string
  /** Stable relationship key. Distinct from any display name (FRONTEND_IMPLEMENTATION_SPEC §5). */
  stableKey: string
  /** UI-only. Inactive stations are excluded from the run but kept in the draft. */
  active: boolean
  preferenceRank: string
  latitudeUdeg: string
  longitudeEastUdeg: string
  ellipsoidalHeightMm: string
  minimumElevationUdeg: string
  rateNumeratorBits: string
  rateDenominatorSeconds: string
  efficiencyNumerator: string
  efficiencyDenominator: string
  /** The original station object, for passthrough of advanced capacity fields. */
  base: StationDTO
}

export interface OrbitForm {
  mode: OrbitMode
  epoch: string
  semiMajorAxisMm: string
  eccentricityPpb: string
  inclinationUdeg: string
  raanUdeg: string
  argumentOfPerigeeUdeg: string
  trueAnomalyUdeg: string
  muM3PerS2: string
  tleLine1: string
  tleLine2: string
}

export type ServiceClass = 'MANDATORY' | 'PRIORITY' | 'BEST_EFFORT'
export type Segmentation = 'ATOMIC_OBJECT' | 'FIXED_CHUNK'

export interface PayloadForm {
  editId: string
  stableKey: string
  displayName: string
  /** Logical transfer size in bytes (measured locally). */
  logicalSizeBytes: string
  /** Storage occupancy in bytes; defaults to the logical size but is a distinct DTO field. */
  storageSizeBytes: string
  readyAt: string
  serviceClass: ServiceClass
  missionPriority: string
  queueSequence: string
  segmentation: Segmentation
  chunkSizeBytes: string
  resumeSupported: boolean
  /** Where the size came from, shown for provenance (e.g. "UTF-8 붙여넣기", "파일: report.bin"). */
  sizeSource: string
  /** UI-only decoration: an emoji shown for this output and streamed down the beam while it is being
   *  transmitted. NOT serialized into the DTO, so it never enters the request, hash, or golden. */
  emoji: string
  /** The original payload object for passthrough of advanced fields; null for a new object. */
  base: PayloadDTO | null
}

const EMOJI_PALETTE = ['🛰️', '📦', '🔥', '🚢', '✈️', '🌊', '🗺️', '📡', '🎥', '📈', '🛢️', '🌎']

/** A stable default emoji for an output, derived from its key so different outputs differ out of the
 *  box. Purely cosmetic; the user can change it. */
export function defaultEmojiFor(key: string): string {
  let hash = 0
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0
  return EMOJI_PALETTE[hash % EMOJI_PALETTE.length]
}

export interface DependencyForm {
  editId: string
  predecessorKey: string
  successorKey: string
  kind: string
}

export interface ScenarioDraft {
  /** UI-only friendly label; never serialized into the strict DTO. */
  scenarioName: string
  /** UI-only display name for this scenario's single satellite (separate from the scenario name).
   *  Set from a satellite preset on load; never serialized into the executable content or hash. */
  satelliteName: string
  /** UI-only satellite provenance/source note (for the satellite preset). Not in the content/hash. */
  satelliteProvenance: string
  /** UI-only flag: the satellite's orbit/settings are an assumption, not measured. Not in content. */
  satelliteIsAssumption: boolean
  presetFixtureId: string
  /** True only when `presetFixtureId` is a packaged public fixture the server can run by id. A
   *  loaded saved scenario is false, so its runs always go through the full snapshot body. */
  presetIsPublicFixture: boolean
  /** Set when this draft was loaded from a saved server scenario (for "save as new revision"). */
  savedScenarioId?: string
  baseContent: FixtureContent
  analysisWindowStart: string
  analysisWindowEnd: string
  analysisMode: 'NETWORK_ONLY' | 'QUEUE_AWARE'
  executionStrategy: 'EXACT_GLOBAL' | 'BOUNDED_APPROXIMATE'
  orbit: OrbitForm
  stations: StationForm[]
  /** Model-output cart. Preserved across a NETWORK_ONLY excursion (excluded from that request). */
  payloads: PayloadForm[]
  /** Payload dependencies (predecessor → successor). A payload referenced here cannot be deleted or
   *  renamed until the dependency is removed. */
  dependencies: DependencyForm[]
}

export class DraftValidationError extends Error {
  readonly fieldPath: string
  constructor(message: string, fieldPath: string) {
    super(message)
    this.name = 'DraftValidationError'
    this.fieldPath = fieldPath
  }
}

function stationForm(station: StationDTO): StationForm {
  const seg = station.capacity.rate_segments[0]
  const eff = station.capacity.active_efficiency
  return {
    editId: nextEditId('gs'),
    stableKey: station.stable_key,
    active: true,
    preferenceRank: String(station.preference_rank),
    latitudeUdeg: String(station.site?.latitude_udeg ?? 0),
    longitudeEastUdeg: String(station.site?.longitude_east_udeg ?? 0),
    ellipsoidalHeightMm: String(station.site?.ellipsoidal_height_mm ?? 0),
    minimumElevationUdeg: String(station.site?.minimum_elevation_udeg ?? 0),
    rateNumeratorBits: String(seg?.numerator_bits ?? 0),
    rateDenominatorSeconds: String(seg?.denominator_seconds ?? 1),
    efficiencyNumerator: String(eff?.numerator ?? 1),
    efficiencyDenominator: String(eff?.denominator ?? 1),
    base: station,
  }
}

function payloadForm(payload: PayloadDTO): PayloadForm {
  return {
    editId: nextEditId('pl'),
    stableKey: payload.stable_key,
    displayName: payload.display_name ?? payload.stable_key,
    logicalSizeBytes: String(payload.logical_size_bytes),
    storageSizeBytes: String(payload.storage_size_bytes),
    readyAt: payload.ready_at,
    serviceClass: payload.service_class,
    missionPriority: String(payload.mission_priority),
    queueSequence: String(payload.queue_sequence),
    segmentation: payload.segmentation,
    chunkSizeBytes: payload.chunk_size_bytes != null ? String(payload.chunk_size_bytes) : '1000000',
    resumeSupported: payload.resume_supported,
    sizeSource: '프리셋',
    emoji: defaultEmojiFor(payload.stable_key),
    base: payload,
  }
}

/** Public constructor for a cart item from a preset output template (re-add via the catalog). */
export function payloadFormFromTemplate(payload: PayloadDTO): PayloadForm {
  return payloadForm(payload)
}

function dependencyForm(dep: Record<string, unknown>): DependencyForm {
  return {
    editId: nextEditId('dep'),
    predecessorKey: String(dep.predecessor_key ?? ''),
    successorKey: String(dep.successor_key ?? ''),
    kind: String(dep.kind ?? 'SEND_AFTER'),
  }
}

/** Stable keys of payloads referenced by any dependency (blocks their deletion/rename). */
export function referencedPayloadKeys(dependencies: DependencyForm[]): Set<string> {
  const set = new Set<string>()
  for (const d of dependencies) {
    if (d.predecessorKey) set.add(d.predecessorKey)
    if (d.successorKey) set.add(d.successorKey)
  }
  return set
}

/** Human descriptions of the dependencies that reference a given payload key. */
export function dependenciesReferencing(
  dependencies: DependencyForm[],
  payloadKey: string,
): DependencyForm[] {
  return dependencies.filter((d) => d.predecessorKey === payloadKey || d.successorKey === payloadKey)
}

export interface NewPayloadOptions {
  stableKey: string
  displayName: string
  logicalSizeBytes: number
  readyAt: string
  queueSequence: number
  sizeSource: string
}

/** A new model-output draft with explicit, valid defaults (ATOMIC_OBJECT, BEST_EFFORT). */
export function createPayloadForm(opts: NewPayloadOptions): PayloadForm {
  return {
    editId: nextEditId('pl'),
    stableKey: opts.stableKey,
    displayName: opts.displayName,
    logicalSizeBytes: String(opts.logicalSizeBytes),
    storageSizeBytes: String(opts.logicalSizeBytes),
    readyAt: opts.readyAt,
    serviceClass: 'BEST_EFFORT',
    missionPriority: '0',
    queueSequence: String(opts.queueSequence),
    segmentation: 'ATOMIC_OBJECT',
    chunkSizeBytes: '1000000',
    resumeSupported: false,
    sizeSource: opts.sizeSource,
    emoji: defaultEmojiFor(opts.stableKey),
    base: null,
  }
}

function buildPayload(form: PayloadForm, index: number): PayloadDTO {
  const path = `payloads.${index}`
  // Start from the original object (passthrough of deadline/expiry/bundle/etc.) or a minimal, valid
  // skeleton for a brand-new output. Editable leaves are then overwritten from the form.
  const base: PayloadDTO =
    form.base != null
      ? structuredClone(form.base)
      : {
          stable_key: form.stableKey,
          logical_size_bytes: 1,
          storage_size_bytes: 1,
          ready_at: form.readyAt,
          service_class: 'BEST_EFFORT',
          deadline_severity: 0,
          mission_priority: 0,
          queue_sequence: 0,
          segmentation: 'ATOMIC_OBJECT',
          resume_supported: false,
          media_type: 'application/octet-stream',
          producer_kind: 'USER_SUPPLIED',
        }
  const logical = parseIntegerField(`${path}.logical_size_bytes`, form.logicalSizeBytes)
  const storage = parseIntegerField(`${path}.storage_size_bytes`, form.storageSizeBytes)
  if (logical <= 0 || storage <= 0) {
    throw new DraftValidationError('출력물 크기는 0보다 커야 합니다.', `${path}.logical_size_bytes`)
  }
  if (!isUtcInstant(form.readyAt)) {
    throw new DraftValidationError('ready_at은 UTC 시각이어야 합니다.', `${path}.ready_at`)
  }
  base.stable_key = form.stableKey
  base.display_name = form.displayName || form.stableKey
  base.logical_size_bytes = logical
  base.storage_size_bytes = storage
  base.ready_at = form.readyAt
  base.service_class = form.serviceClass
  const priority = parseIntegerField(`${path}.mission_priority`, form.missionPriority)
  if (priority < 0 || priority > 100) {
    throw new DraftValidationError('임무 우선순위는 0..100 범위여야 합니다.', `${path}.mission_priority`)
  }
  const queueSeq = parseIntegerField(`${path}.queue_sequence`, form.queueSequence)
  if (queueSeq < 0) {
    throw new DraftValidationError('큐 순번은 0 이상이어야 합니다.', `${path}.queue_sequence`)
  }
  base.mission_priority = priority
  base.queue_sequence = queueSeq
  base.segmentation = form.segmentation
  // Keep segmentation self-consistent with the domain contract (FIXED_CHUNK => chunk + resume;
  // ATOMIC_OBJECT => neither), so the screen selection matches exactly what is sent.
  if (form.segmentation === 'FIXED_CHUNK') {
    const chunk = parseIntegerField(`${path}.chunk_size_bytes`, form.chunkSizeBytes)
    if (chunk <= 0) {
      throw new DraftValidationError('FIXED_CHUNK은 양의 청크 크기가 필요합니다.', `${path}.chunk_size_bytes`)
    }
    base.chunk_size_bytes = chunk
    base.resume_supported = true
  } else {
    delete base.chunk_size_bytes
    base.resume_supported = false
  }
  return base
}

export function draftFromPreset(preset: PresetDescriptor): ScenarioDraft {
  const c = preset.content
  const tb = c.orbit?.two_body
  const tle = c.orbit?.tle
  return {
    scenarioName: preset.title,
    satelliteName: preset.satelliteName ?? '위성',
    satelliteProvenance: preset.provenance,
    satelliteIsAssumption: true,
    presetFixtureId: preset.fixtureId,
    presetIsPublicFixture: preset.isPublicFixture ?? true,
    baseContent: c,
    analysisWindowStart: c.analysis_window.start,
    analysisWindowEnd: c.analysis_window.end,
    analysisMode: c.analysis_mode,
    executionStrategy: c.execution_strategy ?? 'EXACT_GLOBAL',
    orbit: {
      mode: (c.orbit?.kind ?? 'TWO_BODY_V1') as OrbitMode,
      epoch: tb?.epoch ?? c.analysis_window.start,
      semiMajorAxisMm: String(tb?.semi_major_axis_mm ?? 7_078_137_000),
      eccentricityPpb: String(tb?.eccentricity_ppb ?? 0),
      inclinationUdeg: String(tb?.inclination_udeg ?? 0),
      raanUdeg: String(tb?.raan_udeg ?? 0),
      argumentOfPerigeeUdeg: String(tb?.argument_of_perigee_udeg ?? 0),
      trueAnomalyUdeg: String(tb?.true_anomaly_udeg ?? 0),
      muM3PerS2: String(tb?.mu_m3_per_s2 ?? 398_600_441_500_000),
      tleLine1: tle?.line_1 ?? '',
      tleLine2: tle?.line_2 ?? '',
    },
    stations: c.stations.map(stationForm),
    payloads: (c.payloads ?? []).map(payloadForm),
    dependencies: ((c.dependencies as Record<string, unknown>[]) ?? []).map(dependencyForm),
  }
}

/** A fresh, EMPTY scenario for "새 시나리오": no satellite orbit values, no stations, no outputs — the
 *  user fills them in (or loads from the libraries). A valid baseContent (from the ORB fixture) is kept
 *  only for passthrough structure; every editable value is blank so nothing is pre-filled. */
export function emptyDraft(): ScenarioDraft {
  return {
    ...draftFromPreset(ORB_PRESET),
    scenarioName: 'scenario_new',
    satelliteName: '',
    satelliteProvenance: '',
    satelliteIsAssumption: true,
    presetFixtureId: 'scenario-new',
    presetIsPublicFixture: false,
    savedScenarioId: undefined,
    orbit: {
      mode: 'TWO_BODY_V1',
      epoch: '',
      semiMajorAxisMm: '',
      eccentricityPpb: '',
      inclinationUdeg: '',
      raanUdeg: '',
      argumentOfPerigeeUdeg: '',
      trueAnomalyUdeg: '',
      muM3PerS2: '',
      tleLine1: '',
      tleLine2: '',
    },
    stations: [],
    payloads: [],
    dependencies: [],
  }
}

function buildOrbit(form: OrbitForm): OrbitSpecDTO {
  if (form.mode === 'GP_TLE') {
    const l1 = form.tleLine1
    const l2 = form.tleLine2
    if (l1.length !== 69 || l2.length !== 69) {
      throw new DraftValidationError('TLE 각 줄은 정확히 69자여야 합니다.', 'orbit.tle')
    }
    return { kind: 'GP_TLE', tle: { line_1: l1, line_2: l2 } }
  }
  if (!isUtcInstant(form.epoch)) {
    throw new DraftValidationError('epoch은 UTC 시각이어야 합니다.', 'orbit.two_body.epoch')
  }
  const two_body: TwoBodyElementsDTO = {
    epoch: form.epoch,
    semi_major_axis_mm: parseIntegerField('orbit.two_body.semi_major_axis_mm', form.semiMajorAxisMm),
    eccentricity_ppb: parseIntegerField('orbit.two_body.eccentricity_ppb', form.eccentricityPpb),
    inclination_udeg: parseIntegerField('orbit.two_body.inclination_udeg', form.inclinationUdeg),
    raan_udeg: parseIntegerField('orbit.two_body.raan_udeg', form.raanUdeg),
    argument_of_perigee_udeg: parseIntegerField(
      'orbit.two_body.argument_of_perigee_udeg',
      form.argumentOfPerigeeUdeg,
    ),
    true_anomaly_udeg: parseIntegerField('orbit.two_body.true_anomaly_udeg', form.trueAnomalyUdeg),
    mu_m3_per_s2: parseIntegerField('orbit.two_body.mu_m3_per_s2', form.muM3PerS2),
  }
  return { kind: 'TWO_BODY_V1', two_body }
}

/** Public: build the executable orbit spec from the orbit form (throws on invalid input). Used when
 *  saving a satellite preset (the preset's payload stores this OrbitSpecDTO). */
export function orbitSpecFromForm(form: OrbitForm): OrbitSpecDTO {
  return buildOrbit(form)
}

/** Public: convert a stored orbit spec back into an editable orbit form. Used when a satellite preset
 *  is loaded into the current scenario (only the orbit is replaced; stations/cart/window are kept). */
export function orbitFormFromSpec(spec: OrbitSpecDTO, fallbackEpoch: string): OrbitForm {
  const tb = spec.two_body
  const tle = spec.tle
  return {
    mode: (spec.kind ?? 'TWO_BODY_V1') as OrbitMode,
    epoch: tb?.epoch ?? fallbackEpoch,
    semiMajorAxisMm: String(tb?.semi_major_axis_mm ?? 7_078_137_000),
    eccentricityPpb: String(tb?.eccentricity_ppb ?? 0),
    inclinationUdeg: String(tb?.inclination_udeg ?? 0),
    raanUdeg: String(tb?.raan_udeg ?? 0),
    argumentOfPerigeeUdeg: String(tb?.argument_of_perigee_udeg ?? 0),
    trueAnomalyUdeg: String(tb?.true_anomaly_udeg ?? 0),
    muM3PerS2: String(tb?.mu_m3_per_s2 ?? 398_600_441_500_000),
    tleLine1: tle?.line_1 ?? '',
    tleLine2: tle?.line_2 ?? '',
  }
}

function buildStation(form: StationForm, index: number): StationDTO {
  const path = `stations.${index}`
  // Clone the original so advanced capacity fields (evidence, accounted_effects, rate_scope,
  // guards, reserves, measurement point) pass through unchanged.
  const station = structuredClone(form.base)
  station.stable_key = form.stableKey
  station.preference_rank = parseIntegerField(`${path}.preference_rank`, form.preferenceRank)
  station.site = {
    latitude_udeg: parseIntegerField(`${path}.site.latitude_udeg`, form.latitudeUdeg),
    longitude_east_udeg: parseIntegerField(`${path}.site.longitude_east_udeg`, form.longitudeEastUdeg),
    ellipsoidal_height_mm: parseIntegerField(
      `${path}.site.ellipsoidal_height_mm`,
      form.ellipsoidalHeightMm,
    ),
    minimum_elevation_udeg: parseIntegerField(
      `${path}.site.minimum_elevation_udeg`,
      form.minimumElevationUdeg,
    ),
  }
  const numerator = parseIntegerField(`${path}.capacity.rate.numerator_bits`, form.rateNumeratorBits)
  const denominator = parseIntegerField(
    `${path}.capacity.rate.denominator_seconds`,
    form.rateDenominatorSeconds,
  )
  const firstSeg = station.capacity.rate_segments[0]
  if (firstSeg) {
    station.capacity.rate_segments = [
      { ...firstSeg, numerator_bits: numerator, denominator_seconds: denominator },
      ...station.capacity.rate_segments.slice(1),
    ]
  }
  station.capacity.active_efficiency = {
    numerator: parseIntegerField(`${path}.capacity.efficiency.numerator`, form.efficiencyNumerator),
    denominator: parseIntegerField(
      `${path}.capacity.efficiency.denominator`,
      form.efficiencyDenominator,
    ),
  }
  return station
}

/** Public: build one executable StationDTO from a station form (throws on invalid input). Used when
 *  saving a ground-station preset and when adding a library/registered station to the scenario. */
export function stationDtoFromForm(form: StationForm): StationDTO {
  return buildStation(form, 0)
}

/** Build a station FORM from a stored StationDTO (library load / register modal seed). */
export function stationFormFromDto(station: StationDTO): StationForm {
  return stationForm(station)
}

/** Build the executable FixtureContent from the draft, applying edits over the seed. */
export function buildFixtureContent(draft: ScenarioDraft): FixtureContent {
  if (!isUtcInstant(draft.analysisWindowStart) || !isUtcInstant(draft.analysisWindowEnd)) {
    throw new DraftValidationError('분석기간은 UTC 시각이어야 합니다.', 'analysis_window')
  }
  const activeStations = draft.stations.filter((s) => s.active)
  if (activeStations.length === 0) {
    throw new DraftValidationError(
      '활성 지상국이 없습니다. 최소 한 곳을 활성화하세요.',
      'stations',
    )
  }
  const seen = new Set<string>()
  for (const station of activeStations) {
    if (seen.has(station.stableKey)) {
      throw new DraftValidationError(
        `지상국 stable key가 중복됩니다: "${station.stableKey}". 각 활성 지상국은 고유해야 합니다.`,
        'stations',
      )
    }
    seen.add(station.stableKey)
  }
  const content = structuredClone(draft.baseContent)
  content.analysis_window = { start: draft.analysisWindowStart, end: draft.analysisWindowEnd }
  content.analysis_mode = draft.analysisMode
  content.orbit = buildOrbit(draft.orbit)
  content.stations = activeStations.map(buildStation)
  // ORBIT_DERIVED windows are generated by the backend; injected contacts are rejected there.
  content.contacts = []

  const effectiveStrategy =
    draft.analysisMode === 'QUEUE_AWARE' ? draft.executionStrategy : 'EXACT_GLOBAL'

  // Mode gate FIRST — before any payload validation (defect 1). NETWORK_ONLY forbids payloads, a
  // queue policy and non-disabled storage, so its request must not be blocked by validating or
  // building a payload the mode excludes anyway. The draft keeps those inputs for the round trip
  // back to QUEUE_AWARE. `delete` (rather than = []) keeps the request clean and lets a pristine
  // preset stay byte-identical.
  if (draft.analysisMode === 'NETWORK_ONLY') {
    content.payloads = []
    delete content.dependencies
    delete content.synthetic_delivery_events
    delete content.policy_revision_id
    delete content.storage
  } else {
    // QUEUE_AWARE: validate and build the model-output cart.
    const payloadKeys = new Set<string>()
    for (const p of draft.payloads) {
      if (payloadKeys.has(p.stableKey)) {
        throw new DraftValidationError(`출력물 stable key가 중복됩니다: "${p.stableKey}".`, 'payloads')
      }
      payloadKeys.add(p.stableKey)
    }
    content.payloads = draft.payloads.map(buildPayload)
    if (content.payloads.length === 0) {
      throw new DraftValidationError(
        'QUEUE_AWARE 실행에는 최소 한 개의 모델 출력이 필요합니다. 출력물을 추가하거나 NETWORK_ONLY로 전환하세요.',
        'payloads',
      )
    }

    // Dependencies come from the editable draft. A reference to an absent payload is a HARD error,
    // never a silent drop (defect 2): the UI blocks deleting/renaming a referenced payload, so
    // reaching here means an inconsistent graph the user must resolve. Preserve the seed's absence
    // of the key for pristine byte-identity (FE-02/FE-03).
    const present = new Set(content.payloads.map((p) => p.stable_key))
    if (draft.dependencies.length > 0) {
      content.dependencies = draft.dependencies.map((d) => {
        if (!present.has(d.predecessorKey) || !present.has(d.successorKey)) {
          throw new DraftValidationError(
            `의존성이 존재하지 않는 출력물을 참조합니다: "${d.predecessorKey}" → "${d.successorKey}". 의존성을 먼저 제거하거나 출력물을 복원하세요.`,
            'dependencies',
          )
        }
        return { predecessor_key: d.predecessorKey, successor_key: d.successorKey, kind: d.kind }
      })
    } else if ('dependencies' in draft.baseContent) {
      content.dependencies = []
    } else {
      delete content.dependencies
    }

    // Synthetic delivery events (test-harness acks; not editable in the F3 UI) pass through, but a
    // dangling reference is surfaced as an error rather than silently dropped.
    if (Array.isArray(content.synthetic_delivery_events)) {
      for (const e of content.synthetic_delivery_events as Array<Record<string, unknown>>) {
        if (!present.has(String(e.payload_key))) {
          throw new DraftValidationError(
            `synthetic_delivery_event가 존재하지 않는 출력물을 참조합니다: "${String(e.payload_key)}".`,
            'synthetic_delivery_events',
          )
        }
      }
    }
  }
  // execution_strategy is optional and the server defaults to EXACT_GLOBAL when it is OMITTED.
  // Therefore a non-default strategy must ALWAYS be written explicitly — omitting it would silently
  // flip the run to EXACT (this bit a loaded BOUNDED_APPROXIMATE scenario). Only when the effective
  // value IS the default do we mirror the seed's presence/absence, so an unedited public preset that
  // omitted the field stays byte-identical (FE-02/FE-03) and runs by fixture id.
  if (effectiveStrategy !== 'EXACT_GLOBAL') {
    content.execution_strategy = effectiveStrategy
  } else if ('execution_strategy' in draft.baseContent) {
    content.execution_strategy = 'EXACT_GLOBAL'
  } else {
    delete content.execution_strategy
  }
  return content
}

/** True when the built content is byte-identical to the seed fixture. */
export function isPristine(draft: ScenarioDraft): boolean {
  try {
    return deepEqual(buildFixtureContent(draft), draft.baseContent)
  } catch {
    return false
  }
}

/** The run request: a bare fixture id only for an unedited *public* preset, else a full snapshot
 *  (FE-03/FE-04). A loaded saved scenario always uses the snapshot body — its fixture id is not a
 *  packaged public fixture the server can resolve by name. */
export function buildRunRequest(
  draft: ScenarioDraft,
): { fixture: string } | { snapshot: FixtureContent } {
  const content = buildFixtureContent(draft)
  if (draft.presetIsPublicFixture && deepEqual(content, draft.baseContent)) {
    return { fixture: draft.presetFixtureId }
  }
  return { snapshot: content }
}

/**
 * Editing-only state the executable save contract cannot persist, so the UI can warn BEFORE saving
 * instead of dropping it silently (CLOSE-03). Inactive stations have no field in the FixtureDTO, and
 * a NETWORK_ONLY scenario excludes the model-output cart by domain rule.
 */
export function saveScopeWarnings(draft: ScenarioDraft): string[] {
  const warnings: string[] = []
  const inactive = draft.stations.filter((s) => !s.active).length
  if (inactive > 0) {
    warnings.push(
      `비활성 지상국 ${inactive}곳은 저장된 시나리오에 포함되지 않습니다(이번 세션 편집에는 유지됨).`,
    )
  }
  if (draft.analysisMode === 'NETWORK_ONLY' && draft.payloads.length > 0) {
    warnings.push(
      `NETWORK_ONLY로 저장하면 모델 출력 장바구니(${draft.payloads.length}개)는 포함되지 않습니다.`,
    )
  }
  return warnings
}

/**
 * Rebase an edited draft onto the just-saved content WITHOUT discarding the user's editing state.
 * The saved identity (scenario id, base content, non-public) is updated so later saves become new
 * revisions and pristine detection works, but the current stations (including inactive ones),
 * payload cart and dependencies are kept — they must not vanish just because the executable
 * snapshot excludes them (CLOSE-03).
 */
export function rebaseSavedDraft(
  draft: ScenarioDraft,
  savedContent: FixtureContent,
  meta: { scenarioId: string; name: string },
): ScenarioDraft {
  return {
    ...draft,
    scenarioName: meta.name,
    presetFixtureId: savedContent.fixture_id,
    presetIsPublicFixture: false,
    savedScenarioId: meta.scenarioId,
    baseContent: savedContent,
  }
}

/** Rebuild an editable draft from a saved scenario's stored content (F3 load / refresh restore). */
export function draftFromContent(
  content: FixtureContent,
  meta: { scenarioId: string; name: string; satelliteName?: string },
): ScenarioDraft {
  const tb = content.orbit?.two_body
  const tle = content.orbit?.tle
  return {
    scenarioName: meta.name,
    satelliteName: meta.satelliteName ?? '위성',
    satelliteProvenance: '',
    satelliteIsAssumption: true,
    presetFixtureId: content.fixture_id,
    presetIsPublicFixture: false,
    savedScenarioId: meta.scenarioId,
    baseContent: content,
    analysisWindowStart: content.analysis_window.start,
    analysisWindowEnd: content.analysis_window.end,
    analysisMode: content.analysis_mode,
    executionStrategy: content.execution_strategy ?? 'EXACT_GLOBAL',
    orbit: {
      mode: (content.orbit?.kind ?? 'TWO_BODY_V1') as OrbitMode,
      epoch: tb?.epoch ?? content.analysis_window.start,
      semiMajorAxisMm: String(tb?.semi_major_axis_mm ?? 7_078_137_000),
      eccentricityPpb: String(tb?.eccentricity_ppb ?? 0),
      inclinationUdeg: String(tb?.inclination_udeg ?? 0),
      raanUdeg: String(tb?.raan_udeg ?? 0),
      argumentOfPerigeeUdeg: String(tb?.argument_of_perigee_udeg ?? 0),
      trueAnomalyUdeg: String(tb?.true_anomaly_udeg ?? 0),
      muM3PerS2: String(tb?.mu_m3_per_s2 ?? 398_600_441_500_000),
      tleLine1: tle?.line_1 ?? '',
      tleLine2: tle?.line_2 ?? '',
    },
    stations: content.stations.map(stationForm),
    payloads: (content.payloads ?? []).map(payloadForm),
    dependencies: ((content.dependencies as Record<string, unknown>[]) ?? []).map(dependencyForm),
  }
}
