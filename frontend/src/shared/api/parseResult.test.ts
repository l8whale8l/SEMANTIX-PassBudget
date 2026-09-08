import { describe, expect, it } from 'vitest'
import { ContractError, parseRunResult, parseRunResultsEnvelope } from './parseResult'
import orbEnvelope from '../../test/fixtures/orb_results_envelope.json'
import netonlyEnvelope from '../../test/fixtures/netonly_results_envelope.json'

// Deep clone so a test's mutation never leaks into another test's fixture.
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T

describe('parseRunResultsEnvelope on real backend responses', () => {
  it('accepts the QUEUE_AWARE ORB envelope', () => {
    expect(() => parseRunResultsEnvelope(clone(orbEnvelope))).not.toThrow()
  })

  it('accepts the NETWORK_ONLY envelope with nullable byte metrics', () => {
    // In NETWORK_ONLY stranded/allocated/remaining are null; validation must allow null, not crash.
    const env = clone(netonlyEnvelope) as { result: { metrics: Record<string, unknown> } }
    expect(env.result.metrics.stranded_capacity_bytes).toBeNull()
    expect(() => parseRunResultsEnvelope(env)).not.toThrow()
  })

  it('preserves unknown fields it does not validate', () => {
    const env = clone(orbEnvelope) as Record<string, unknown> & { result: Record<string, unknown> }
    env.result.some_future_field = { nested: 1 }
    const parsed = parseRunResultsEnvelope(env)
    expect((parsed.result as Record<string, unknown>).some_future_field).toEqual({ nested: 1 })
  })
})

describe('parseRunResult rejects contract drift (correction 5)', () => {
  it('throws when a required field is missing', () => {
    const r = clone(orbEnvelope).result as Record<string, unknown>
    delete r.calculation_status
    expect(() => parseRunResult(r)).toThrow(ContractError)
  })

  it('throws on a wrong type', () => {
    const r = clone(orbEnvelope).result as { metrics: Record<string, unknown> }
    r.metrics.scheduled_unique_capacity_bytes = '526555476' // string, not number
    expect(() => parseRunResult(r)).toThrow(ContractError)
  })

  it('throws when an integer has lost precision beyond 2^53', () => {
    const r = clone(orbEnvelope).result as { metrics: Record<string, unknown> }
    // 2^53 (unsafe): Number() rounds the "...993" input; still integer-but-unsafe, which we reject.
    r.metrics.scheduled_unique_capacity_bytes = Number('9007199254740993')
    expect(() => parseRunResult(r)).toThrow(ContractError)
  })

  it('throws on a malformed nested array item', () => {
    const r = clone(orbEnvelope).result as { geometric_accesses: unknown[] }
    ;(r.geometric_accesses[0] as Record<string, unknown>).true_aos = 42 // not a string
    expect(() => parseRunResult(r)).toThrow(ContractError)
  })

  it('tolerates an unknown status string (enum membership is not asserted here)', () => {
    const r = clone(orbEnvelope).result as Record<string, unknown>
    r.calculation_status = 'SOME_FUTURE_STATUS'
    expect(() => parseRunResult(r)).not.toThrow()
  })
})
