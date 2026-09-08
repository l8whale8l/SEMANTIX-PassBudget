// Runtime validation of the free-form `/results` envelope.
//
// The server types the result as a dict, so the UI cannot trust its shape at compile time. We
// check the fields the UI actually reads — including nested array-item fields and nullable numbers —
// and fail loudly with a contract error if a required one is missing or the wrong type. That
// surfaces a version/contract drift instead of rendering `undefined` as a number
// (FRONTEND_API_INTEGRATION §3, correction 5). Unknown fields are preserved untouched.

import type { DailyBudget, RunResult, RunResultsEnvelope } from './types'

export class ContractError extends Error {
  readonly path: string
  constructor(message: string, path: string) {
    super(`결과 계약 불일치 (${path}): ${message}`)
    this.name = 'ContractError'
    this.path = path
  }
}

function obj(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new ContractError('객체가 필요합니다.', path)
  }
  return value as Record<string, unknown>
}

function num(value: unknown, path: string): number {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new ContractError('숫자가 필요합니다.', path)
  }
  // An integer beyond 2^53 has already lost precision by the time JSON.parse produced it.
  if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
    throw new ContractError('정수가 안전 범위를 벗어나 정밀도가 손실되었습니다.', path)
  }
  return value
}

function numOrNull(value: unknown, path: string): number | null {
  if (value === null) return null
  return num(value, path)
}

function str(value: unknown, path: string): string {
  if (typeof value !== 'string') throw new ContractError('문자열이 필요합니다.', path)
  return value
}

function strOrNull(value: unknown, path: string): string | null {
  if (value === null) return null
  return str(value, path)
}

function arr(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new ContractError('배열이 필요합니다.', path)
  return value
}

function bool(value: unknown, path: string): boolean {
  if (typeof value !== 'boolean') throw new ContractError('불리언이 필요합니다.', path)
  return value
}

export function parseRunResult(raw: unknown): RunResult {
  const r = obj(raw, 'result')
  str(r.analysis_mode, 'result.analysis_mode')
  str(r.calculation_status, 'result.calculation_status')
  str(r.decision_grade, 'result.decision_grade')
  str(r.contact_source, 'result.contact_source')
  str(r.safety_notice, 'result.safety_notice')

  const metrics = obj(r.metrics, 'result.metrics')
  num(metrics.geometric_contact_count, 'result.metrics.geometric_contact_count')
  num(metrics.scheduled_session_count, 'result.metrics.scheduled_session_count')
  num(metrics.scheduled_unique_capacity_bytes, 'result.metrics.scheduled_unique_capacity_bytes')
  num(metrics.candidate_capacity_sum_bytes, 'result.metrics.candidate_capacity_sum_bytes')
  num(metrics.scheduled_session_duration_us, 'result.metrics.scheduled_session_duration_us')
  // These are genuinely nullable (NETWORK_ONLY has no payload layer): null is allowed, a wrong
  // type is not.
  numOrNull(metrics.payload_allocated_bytes, 'result.metrics.payload_allocated_bytes')
  numOrNull(metrics.payload_remaining_bytes, 'result.metrics.payload_remaining_bytes')
  numOrNull(metrics.stranded_capacity_bytes, 'result.metrics.stranded_capacity_bytes')

  const gap = obj(metrics.scheduled_session_gap, 'result.metrics.scheduled_session_gap')
  str(gap.scope, 'result.metrics.scheduled_session_gap.scope')
  numOrNull(gap.max_us, 'result.metrics.scheduled_session_gap.max_us')

  arr(metrics.stations, 'result.metrics.stations').forEach((s, i) => {
    const st = obj(s, `result.metrics.stations.${i}`)
    str(st.station_key, `result.metrics.stations.${i}.station_key`)
    num(st.geometric_contact_count, `result.metrics.stations.${i}.geometric_contact_count`)
    num(st.candidate_capacity_sum_bytes, `result.metrics.stations.${i}.candidate_capacity_sum_bytes`)
    str(st.decision_grade, `result.metrics.stations.${i}.decision_grade`)
  })

  arr(r.geometric_accesses, 'result.geometric_accesses').forEach((a, i) => {
    const ac = obj(a, `result.geometric_accesses.${i}`)
    str(ac.stable_key, `result.geometric_accesses.${i}.stable_key`)
    str(ac.station_key, `result.geometric_accesses.${i}.station_key`)
    str(ac.true_aos, `result.geometric_accesses.${i}.true_aos`)
    str(ac.true_los, `result.geometric_accesses.${i}.true_los`)
    // Orbit geometry is present only for ORBIT_DERIVED accesses; a SYNTHETIC_INJECTED access omits
    // it. Validate the type only when the field is present.
    if (ac.maximum_elevation_udeg !== undefined) {
      numOrNull(ac.maximum_elevation_udeg, `result.geometric_accesses.${i}.maximum_elevation_udeg`)
    }
    if (ac.maximum_elevation_at !== undefined) {
      strOrNull(ac.maximum_elevation_at, `result.geometric_accesses.${i}.maximum_elevation_at`)
    }
  })

  arr(r.scheduled_sessions, 'result.scheduled_sessions').forEach((s, i) => {
    const se = obj(s, `result.scheduled_sessions.${i}`)
    str(se.stable_key, `result.scheduled_sessions.${i}.stable_key`)
    str(se.station_key, `result.scheduled_sessions.${i}.station_key`)
    num(se.capacity_bytes, `result.scheduled_sessions.${i}.capacity_bytes`)
    arr(se.reason_codes, `result.scheduled_sessions.${i}.reason_codes`)
  })

  arr(r.payload_progress, 'result.payload_progress').forEach((p, i) => {
    const pp = obj(p, `result.payload_progress.${i}`)
    str(pp.payload_key, `result.payload_progress.${i}.payload_key`)
    num(pp.logical_size_bytes, `result.payload_progress.${i}.logical_size_bytes`)
    num(pp.allocated_bytes, `result.payload_progress.${i}.allocated_bytes`)
    num(pp.remaining_bytes, `result.payload_progress.${i}.remaining_bytes`)
    str(pp.state, `result.payload_progress.${i}.state`)
  })

  // Per-allocation transfer segments (time-resolved), used by the delivery-progress panel (§8). Each
  // carries a [start, end] within a session and the bytes moved; validate the fields that panel reads.
  arr(r.payload_allocations, 'result.payload_allocations').forEach((a, i) => {
    const al = obj(a, `result.payload_allocations.${i}`)
    str(al.payload_key, `result.payload_allocations.${i}.payload_key`)
    str(al.start, `result.payload_allocations.${i}.start`)
    str(al.end, `result.payload_allocations.${i}.end`)
    num(al.allocated_bytes, `result.payload_allocations.${i}.allocated_bytes`)
  })

  arr(r.warnings, 'result.warnings').forEach((w, i) => {
    str(obj(w, `result.warnings.${i}`).code, `result.warnings.${i}.code`)
  })

  const opt = obj(r.optimization, 'result.optimization')
  str(opt.optimization_status, 'result.optimization.optimization_status')
  bool(opt.globally_optimal, 'result.optimization.globally_optimal')
  obj(r.orbit_dependency, 'result.orbit_dependency')

  // Shape verified; hand back the original object so unknown fields survive for later features.
  return raw as RunResult
}

export function parseRunResultsEnvelope(raw: unknown): RunResultsEnvelope {
  const e = obj(raw, 'envelope')
  str(e.run_id, 'run_id')
  str(e.input_snapshot_hash, 'input_snapshot_hash')
  str(e.result_content_hash, 'result_content_hash')
  parseRunResult(e.result)
  return raw as RunResultsEnvelope
}

export function parseDailyBudget(raw: unknown): DailyBudget {
  const b = obj(raw, 'daily-budget')
  str(b.run_id, 'daily-budget.run_id')
  str(b.aggregation_basis, 'daily-budget.aggregation_basis')
  str(b.calculation_status, 'daily-budget.calculation_status')
  str(b.notice, 'daily-budget.notice')
  bool(b.sum_preserved, 'daily-budget.sum_preserved')
  numOrNull(b.period_scheduled_unique_capacity_bytes, 'daily-budget.period_scheduled_unique_capacity_bytes')
  num(b.period_scheduled_capacity_from_days_bytes, 'daily-budget.period_scheduled_capacity_from_days_bytes')
  if (b.analysis_window !== null) {
    const w = obj(b.analysis_window, 'daily-budget.analysis_window')
    str(w.start, 'daily-budget.analysis_window.start')
    str(w.end, 'daily-budget.analysis_window.end')
  }
  arr(b.days, 'daily-budget.days').forEach((d, i) => {
    const day = obj(d, `daily-budget.days.${i}`)
    str(day.utc_date, `daily-budget.days.${i}.utc_date`)
    bool(day.is_partial, `daily-budget.days.${i}.is_partial`)
    num(day.geometric_contact_count, `daily-budget.days.${i}.geometric_contact_count`)
    num(day.scheduled_session_count, `daily-budget.days.${i}.scheduled_session_count`)
    num(day.scheduled_capacity_bytes, `daily-budget.days.${i}.scheduled_capacity_bytes`)
    num(day.candidate_session_count, `daily-budget.days.${i}.candidate_session_count`)
    num(day.candidate_capacity_sum_bytes, `daily-budget.days.${i}.candidate_capacity_sum_bytes`)
  })
  return raw as DailyBudget
}
