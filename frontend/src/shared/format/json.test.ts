import { describe, expect, it } from 'vitest'
import { deepEqual, parseIntegerField, stableStringify, UnsafeIntegerError } from './json'

describe('parseIntegerField', () => {
  it('parses a normal integer string exactly', () => {
    expect(parseIntegerField('site.latitude_udeg', '37600000')).toBe(37_600_000)
    expect(parseIntegerField('x', '-180000000')).toBe(-180_000_000)
  })

  it('parses a large-but-safe value used by the golden orbit (mu, semi-major axis)', () => {
    expect(parseIntegerField('mu', '398600441500000')).toBe(398_600_441_500_000)
    expect(parseIntegerField('sma', '7078137000')).toBe(7_078_137_000)
  })

  it('rejects non-integer syntax without coercing', () => {
    expect(() => parseIntegerField('x', '3.5')).toThrow()
    expect(() => parseIntegerField('x', '')).toThrow()
    expect(() => parseIntegerField('x', '1e6')).toThrow()
  })

  it('refuses an out-of-safe-range integer instead of rounding it', () => {
    const raw = '9007199254740993' // 2^53 + 1
    expect(() => parseIntegerField('x', raw)).toThrow(UnsafeIntegerError)
    try {
      parseIntegerField('deep.field', raw)
    } catch (err) {
      expect((err as UnsafeIntegerError).rawValue).toBe(raw)
      expect((err as UnsafeIntegerError).fieldPath).toBe('deep.field')
    }
  })
})

describe('stable identity', () => {
  it('is key-order independent', () => {
    expect(stableStringify({ b: 1, a: 2 })).toBe(stableStringify({ a: 2, b: 1 }))
    expect(deepEqual({ a: [1, { y: 2, x: 3 }] }, { a: [1, { x: 3, y: 2 }] })).toBe(true)
  })

  it('distinguishes different content', () => {
    expect(deepEqual({ a: 1 }, { a: 2 })).toBe(false)
  })
})
