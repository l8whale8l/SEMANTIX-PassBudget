import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, NetworkError } from './client'

const errorEnvelope = (code: string, message: string) => ({
  error: { code, message, scope: 'comparison', field_paths: [], affected_branches: [], details: {} },
})

function mockFetch(response: Partial<Response> & { jsonBody?: unknown; textBody?: string }) {
  return vi.fn().mockResolvedValue({
    ok: response.ok ?? true,
    status: response.status ?? 200,
    text: async () => response.textBody ?? JSON.stringify(response.jsonBody ?? {}),
    json: async () => response.jsonBody ?? {},
  } as Response)
}

beforeEach(() => vi.restoreAllMocks())
afterEach(() => vi.restoreAllMocks())

describe('api.createComparison error mapping (FE-20)', () => {
  it('maps a 404 error envelope to a typed ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({ ok: false, status: 404, jsonBody: errorEnvelope('RUN_NOT_FOUND', 'A comparison run identifier does not exist.') }),
    )
    await expect(api.createComparison('a', 'b')).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      code: 'RUN_NOT_FOUND',
    })
    await expect(api.createComparison('a', 'b')).rejects.toBeInstanceOf(ApiError)
  })

  it('falls back to a safe generic error when the body is not an envelope (e.g. 413)', async () => {
    vi.stubGlobal('fetch', mockFetch({ ok: false, status: 413, textBody: 'Payload Too Large' }))
    await expect(api.createComparison('a', 'b')).rejects.toMatchObject({ status: 413, code: 'HTTP_413' })
  })

  it('raises a NetworkError (not possibly-delivered for a POST is false only on GET) on transport failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.createComparison('a', 'b')).rejects.toBeInstanceOf(NetworkError)
  })
})

describe('api.getReportText (FE-19)', () => {
  it('returns the plain-text report body', async () => {
    vi.stubGlobal('fetch', mockFetch({ ok: true, status: 200, textBody: 'REPORT BODY' }))
    await expect(api.getReportText('run-1')).resolves.toBe('REPORT BODY')
  })

  it('maps a 501 to an ApiError instead of returning empty text', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({ ok: false, status: 501, jsonBody: errorEnvelope('RESULT_DOCUMENT_NOT_PERSISTED', 'x') }),
    )
    await expect(api.getReportText('run-1')).rejects.toBeInstanceOf(ApiError)
  })
})

describe('api.getRevisionContent (FE-16)', () => {
  it('returns the saved content body', async () => {
    const body = { revision_id: 'r1', scenario_id: 's1', content: { fixture_id: 'X' } }
    vi.stubGlobal('fetch', mockFetch({ ok: true, status: 200, jsonBody: body }))
    await expect(api.getRevisionContent('r1')).resolves.toMatchObject({ scenario_id: 's1' })
  })

  it('maps a 404 to SCENARIO_REVISION_NOT_FOUND', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({ ok: false, status: 404, jsonBody: errorEnvelope('SCENARIO_REVISION_NOT_FOUND', 'x') }),
    )
    await expect(api.getRevisionContent('nope')).rejects.toMatchObject({ code: 'SCENARIO_REVISION_NOT_FOUND' })
  })
})

describe('api.getDailyBudget (F4)', () => {
  const okBody = {
    run_id: 'run-1',
    analysis_window: { start: '2026-09-03T00:00:00.000000Z', end: '2026-09-04T00:00:00.000000Z' },
    aggregation_basis: 'UTC_DATE_OF_SESSION_START',
    calculation_status: 'COMPUTED',
    period_scheduled_unique_capacity_bytes: 100,
    period_scheduled_capacity_from_days_bytes: 100,
    sum_preserved: true,
    days: [
      {
        utc_date: '2026-09-03',
        is_partial: false,
        geometric_contact_count: 1,
        scheduled_session_count: 1,
        scheduled_capacity_bytes: 100,
        candidate_session_count: 1,
        candidate_capacity_sum_bytes: 100,
      },
    ],
    notice: 'n',
  }

  it('returns the validated per-date budget', async () => {
    vi.stubGlobal('fetch', mockFetch({ ok: true, status: 200, jsonBody: okBody }))
    await expect(api.getDailyBudget('run-1')).resolves.toMatchObject({
      aggregation_basis: 'UTC_DATE_OF_SESSION_START',
      sum_preserved: true,
    })
  })

  it('maps a 404 to a typed ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({ ok: false, status: 404, jsonBody: errorEnvelope('RUN_NOT_FOUND', 'x') }),
    )
    await expect(api.getDailyBudget('nope')).rejects.toBeInstanceOf(ApiError)
  })

  it('raises a ContractError when a required day field is missing', async () => {
    const broken = { ...okBody, days: [{ utc_date: '2026-09-03' }] }
    vi.stubGlobal('fetch', mockFetch({ ok: true, status: 200, jsonBody: broken }))
    await expect(api.getDailyBudget('run-1')).rejects.toThrow(/결과 계약 불일치/)
  })
})
