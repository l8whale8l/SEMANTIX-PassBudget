// TypeScript mirrors of the backend contract.
//
// Request shapes track `interfaces/dto.py` (strict, extra="forbid"); result shapes track the
// observed `/results` envelope. The result `result` object is a free dict on the server, so we
// type the fields the UI reads and keep unknown fields via an index signature rather than `any`
// (FRONTEND_API_INTEGRATION §3). Runtime validation lives in `parseResult.ts`.

// ----------------------------------------------------------------- request (FixtureDTO)

export interface RationalDTO {
  numerator: number
  denominator: number
}

export interface RateSegmentDTO {
  ordinal: number
  start_offset_us: number
  end_offset_us: number
  numerator_bits: number
  denominator_seconds: number
}

export interface CapacityDTO {
  provider: string
  rate_semantics?: string | null
  acquisition_guard_us: number
  release_guard_us: number
  rate_segments: RateSegmentDTO[]
  fixed_capacity_bytes?: number | null
  byte_reserve?: number
  active_efficiency?: RationalDTO | null
  rate_unknown?: boolean
  evidence_state: string
  source_revision_id?: string | null
  rationale?: string | null
  time_reserves?: Array<{ start_offset_us: number; end_offset_us: number }>
  measurement_point?: string | null
  rate_scope?: string | null
  accounted_effects?: string[]
}

export interface GeodeticSiteDTO {
  latitude_udeg: number
  longitude_east_udeg: number
  ellipsoidal_height_mm: number
  minimum_elevation_udeg: number
}

export interface StationDTO {
  stable_key: string
  preference_rank: number
  capacity: CapacityDTO
  site?: GeodeticSiteDTO | null
}

export interface TleElementsDTO {
  line_1: string
  line_2: string
}

export interface TwoBodyElementsDTO {
  epoch: string
  semi_major_axis_mm: number
  eccentricity_ppb: number
  inclination_udeg: number
  raan_udeg: number
  argument_of_perigee_udeg: number
  true_anomaly_udeg: number
  mu_m3_per_s2: number
}

export interface OrbitSpecDTO {
  kind: 'GP_TLE' | 'TWO_BODY_V1'
  tle?: TleElementsDTO | null
  two_body?: TwoBodyElementsDTO | null
}

export interface IntervalDTO {
  start: string
  end: string
}

export interface PayloadDTO {
  stable_key: string
  logical_size_bytes: number
  storage_size_bytes: number
  ready_at: string
  service_class: 'MANDATORY' | 'PRIORITY' | 'BEST_EFFORT'
  deadline_at?: string | null
  deadline_severity: number
  mission_priority: number
  queue_sequence: number
  segmentation: 'ATOMIC_OBJECT' | 'FIXED_CHUNK'
  chunk_size_bytes?: number | null
  resume_supported: boolean
  display_name?: string | null
  media_type?: string
  producer_kind?: 'MODEL_DERIVED' | 'USER_SUPPLIED'
  [key: string]: unknown
}

/**
 * The executable scenario body. Only the fields the F1 UI edits are named strongly; the rest of a
 * preset (storage, dependencies, advanced payload fields, evidence) is carried through unchanged so
 * a form round-trip never drops a hidden advanced value (FE-02). The index signature holds those
 * passthrough fields without resorting to `any`.
 */
export interface FixtureContent {
  schema_version: string
  fixture_id: string
  analysis_mode: 'NETWORK_ONLY' | 'QUEUE_AWARE'
  analysis_window: IntervalDTO
  stations: StationDTO[]
  contacts: unknown[]
  source_revision_id: string
  safety_notice: string
  decision_question?: string
  policy_revision_id?: string | null
  payloads?: PayloadDTO[]
  dependencies?: unknown[]
  storage?: unknown
  contact_source: 'SYNTHETIC_INJECTED' | 'ORBIT_DERIVED'
  synthetic_delivery_events?: unknown[]
  execution_strategy?: 'EXACT_GLOBAL' | 'BOUNDED_APPROXIMATE'
  orbit?: OrbitSpecDTO | null
  [key: string]: unknown
}

export type CreateRunRequest =
  | { fixture: string }
  | { snapshot: FixtureContent }
  | { snapshot_id: string }

// ----------------------------------------------------------------- responses

export interface StageResponse {
  stage_code: string
  stage_ordinal: number
  status: string
  row_count: number
}

export interface RunMetadata {
  run_id: string
  status: string
  input_snapshot_hash: string
  result_content_hash: string
  run_record_hash: string
  stages: StageResponse[]
}

export interface ReasonCode {
  code: string
  [key: string]: unknown
}

export interface GapMetric {
  scope: string
  max_us: number | null
  [key: string]: unknown
}

export interface StationMetric {
  station_key: string
  geometric_contact_count: number
  candidate_capacity_sum_bytes: number
  calculation_status: string
  decision_grade: string
  [key: string]: unknown
}

export interface ResultMetrics {
  geometric_contact_count: number
  modeled_candidate_count: number
  scheduled_session_count: number
  candidate_capacity_sum_bytes: number
  scheduled_unique_capacity_bytes: number
  suppressed_capacity_bytes: number
  stranded_capacity_bytes: number
  geometric_duration_us: number
  scheduled_session_duration_us: number
  geometric_access_gap: GapMetric
  scheduled_session_gap: GapMetric
  payload_allocated_bytes: number | null
  payload_remaining_bytes: number | null
  stations: StationMetric[]
  [key: string]: unknown
}

export interface GeometricAccess {
  stable_key: string
  station_key: string
  true_aos: string
  true_los: string
  calculation_status: string
  decision_grade: string
  maximum_elevation_udeg: number | null
  maximum_elevation_at: string | null
  clipped_start: boolean
  clipped_end: boolean
  [key: string]: unknown
}

export interface ScheduledSession {
  stable_key: string
  candidate_stable_key: string
  station_key: string
  selection_ordinal: number
  usable_start: string
  usable_end: string
  capacity_bytes: number
  calculation_status: string
  decision_grade: string
  reason_codes: ReasonCode[]
  [key: string]: unknown
}

export interface PayloadProgress {
  payload_key: string
  logical_size_bytes: number
  allocated_bytes: number
  remaining_bytes: number
  state: string
  modeled_tx_complete_at: string | null
  partial_transfer_end_at: string | null
  deadline_status: string | null
  reason_codes: ReasonCode[]
  [key: string]: unknown
}

export interface PayloadAllocation {
  payload_key: string
  session_key: string
  station_key: string
  allocation_ordinal: number
  logical_offset_start: number
  /** The transfer segment's planned start/end within the session (ISO UTC). */
  start: string
  end: string
  allocated_bytes: number
  remaining_bytes_after: number
  modeled_tx_complete_at: string | null
  [key: string]: unknown
}

export interface Optimization {
  execution_strategy: string
  optimization_status: string
  globally_optimal: boolean
  optimality_gap: unknown
  algorithm_revision: string
  [key: string]: unknown
}

export interface OrbitDependency {
  calculation_status: string
  value?: unknown
  [key: string]: unknown
}

export interface Warning {
  code: string
  scope_stable_key?: string
  [key: string]: unknown
}

export interface RunResult {
  schema_version: string
  fixture_id: string
  analysis_mode: string
  calculation_status: string
  decision_grade: string
  safety_notice: string
  contact_source: string
  optimization: Optimization
  orbit_dependency: OrbitDependency
  geometric_accesses: GeometricAccess[]
  scheduled_sessions: ScheduledSession[]
  candidate_sessions: unknown[]
  payload_progress: PayloadProgress[]
  payload_allocations: PayloadAllocation[]
  metrics: ResultMetrics
  warnings: Warning[]
  [key: string]: unknown
}

export interface RunResultsEnvelope {
  run_id: string
  input_snapshot_hash: string
  result_content_hash: string
  result: RunResult
}

// ----------------------------------------------------------------- daily budget (F4)

/** One UTC calendar date's re-aggregated budget. Sessions are attributed wholly to their start
 *  day (AGGREGATION_BASIS = UTC_DATE_OF_SESSION_START). */
export interface DailyBudgetDay {
  utc_date: string
  is_partial: boolean
  geometric_contact_count: number
  scheduled_session_count: number
  scheduled_capacity_bytes: number
  candidate_session_count: number
  candidate_capacity_sum_bytes: number
}

export interface DailyBudget {
  run_id: string
  analysis_window: { start: string; end: string } | null
  aggregation_basis: string
  calculation_status: string
  period_scheduled_unique_capacity_bytes: number | null
  period_scheduled_capacity_from_days_bytes: number
  sum_preserved: boolean
  days: DailyBudgetDay[]
  notice: string
}

// ----------------------------------------------------------------- lifecycle (F3)

export interface ScenarioRevisionMeta {
  revision_id: string
  scenario_id: string
  revision_no: number
  lifecycle_status: string
  schema_version: string
  based_on_revision_id?: string | null
  semantic_hash?: string | null
  published_at?: string | null
}

export interface ScenarioResponse {
  scenario_id: string
  stable_key: string
  name: string
  description?: string | null
  is_preset: boolean
  current_revision_id: string | null
  revisions: ScenarioRevisionMeta[]
  recent_run_ids: string[]
}

export interface ScenarioRevisionContent {
  revision_id: string
  scenario_id: string
  revision_no: number
  lifecycle_status: string
  schema_version: string
  content: FixtureContent
}

export interface SnapshotResponse {
  snapshot_id: string
  scenario_revision_id: string
  schema_version: string
  canonicalization_revision: string
  input_snapshot_hash: string
  validation_status: string
  validation_code?: string | null
}

// ----------------------------------------------------------------- profiles (satellite presets)

/** A satellite preset stored as a SPACECRAFT profile: the opaque revision payload we define. */
export interface SatellitePresetPayload {
  schema: 'passbudget-satellite-preset-1'
  name: string
  provenance: string
  isAssumption: boolean
  orbit: OrbitSpecDTO
}

/** A ground-station preset stored as a GROUND_STATION profile: opaque revision payload we define.
 *  `station` is a full executable StationDTO so a saved station loads back exactly (advanced capacity
 *  fields included); `name` is the friendly display label shown in the library list. */
export interface GroundStationPresetPayload {
  schema: 'passbudget-ground-station-preset-1'
  name: string
  station: StationDTO
}

/** Any opaque profile-revision payload this app defines. */
export type ProfilePresetPayload = SatellitePresetPayload | GroundStationPresetPayload

export interface ProfileRevisionMeta {
  revision_id: string
  profile_id: string
  profile_kind: string
  revision_no: number
  lifecycle_status: string
  schema_version: string
  label: string
  semantic_hash?: string | null
  published_at?: string | null
}

export interface ProfileResponse {
  profile_id: string
  stable_key: string
  kind: string
  name: string
  description?: string | null
  is_preset: boolean
  current_revision_id: string | null
  revisions: ProfileRevisionMeta[]
}

export interface ProfileRevisionContent {
  revision_id: string
  profile_id: string
  profile_kind: string
  revision_no: number
  lifecycle_status: string
  schema_version: string
  label: string
  payload: unknown
}

export interface ComparisonRatio {
  numerator: string
  denominator: string
}

export interface ComparisonMetric {
  metric: string
  scope_code: string
  station_key: string | null
  payload_key: string | null
  unit: string
  baseline: number | null
  candidate: number | null
  absolute_delta: number | null
  candidate_to_baseline_ratio: ComparisonRatio | null
  comparable: boolean
  reason_codes: ReasonCode[]
  [key: string]: unknown
}

export interface ComparisonOptimization {
  execution_strategy: string
  optimization_status: string
  globally_optimal: boolean
  [key: string]: unknown
}

export interface ComparisonResponse {
  schema_version: string
  baseline_fixture_id: string
  candidate_fixture_id: string
  baseline_decision_grade: string
  candidate_decision_grade: string
  baseline_optimization: ComparisonOptimization
  candidate_optimization: ComparisonOptimization
  metrics: ComparisonMetric[]
  warnings: Warning[]
  safety_notice: string
  [key: string]: unknown
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    scope: string
    field_paths: string[]
    affected_branches: string[]
    details: Record<string, unknown>
  }
}
