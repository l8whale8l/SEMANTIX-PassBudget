import { describe, expect, it } from 'vitest'
import { formatAnalysisWindow, formatUtc, formatUtcClock, isUtcInstant, parseUtcInstant } from './time'

describe('UTC instant parsing', () => {
  it('preserves microsecond digits that a Date would truncate', () => {
    const t = parseUtcInstant('2026-09-03T03:11:44.916905Z')
    expect(t.fraction).toBe('916905')
    // The exact tail survives a format round-trip.
    expect(formatUtc('2026-09-03T03:11:44.916905Z')).toBe('2026-09-03 03:11:44.916905 UTC')
  })

  it('handles an instant with no fractional part', () => {
    expect(formatUtc('2026-09-04T00:00:00Z')).toBe('2026-09-04 00:00:00 UTC')
  })

  it('rejects a non-UTC or malformed string', () => {
    expect(isUtcInstant('2026-09-03T03:11:44+09:00')).toBe(false)
    expect(() => parseUtcInstant('nonsense')).toThrow()
  })

  it('formats a compact clock', () => {
    expect(formatUtcClock('2026-09-03T03:11:44.916905Z')).toBe('03:11:44')
  })

  it('does not mutate the stored value when trimming display digits', () => {
    const raw = '2026-09-03T03:11:44.916905Z'
    expect(formatUtc(raw, 3)).toBe('2026-09-03 03:11:44.916 UTC')
    expect(parseUtcInstant(raw).fraction).toBe('916905')
  })
})

describe('analysis-window label (spec §3-2)', () => {
  it('shows date range + duration + timezone', () => {
    expect(formatAnalysisWindow('2026-09-03T00:00:00Z', '2026-09-04T00:00:00Z')).toBe(
      '9월 3일 → 9월 4일 · 24시간 · UTC',
    )
  })

  it('formats a sub-day window with hours and minutes', () => {
    expect(formatAnalysisWindow('2026-09-03T06:00:00Z', '2026-09-03T07:30:00Z')).toBe(
      '9월 3일 → 9월 3일 · 1시간 30분 · UTC',
    )
  })

  it('formats a multi-day window', () => {
    expect(formatAnalysisWindow('2026-09-03T00:00:00Z', '2026-09-06T00:00:00Z')).toBe(
      '9월 3일 → 9월 6일 · 72시간 · UTC',
    )
  })
})
