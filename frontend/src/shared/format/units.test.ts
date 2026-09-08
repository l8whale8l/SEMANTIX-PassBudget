import { describe, expect, it } from 'vitest'
import {
  bytesToExactBytes,
  bytesToMbDisplay,
  bytesToMbExact,
  formatBytesAdaptive,
  microsToHms,
  microsToSecondsDisplay,
  microsToSecondsExact,
} from './units'

describe('byte -> MB conversion', () => {
  it('keeps full precision in the exact form (golden: 526,555,476 B)', () => {
    expect(bytesToMbExact(526_555_476)).toBe('526.555476')
  })

  it('rounds only in the display form (golden screen value 526.56 MB)', () => {
    expect(bytesToMbDisplay(526_555_476)).toBe('526.56')
  })

  it('does not drop trailing micro digits', () => {
    expect(bytesToMbExact(4_555_476)).toBe('4.555476')
    expect(bytesToMbDisplay(4_555_476)).toBe('4.56')
  })

  it('renders exact multiples without a rounding artifact', () => {
    expect(bytesToMbExact(522_000_000)).toBe('522.000000')
    expect(bytesToMbDisplay(522_000_000)).toBe('522.00')
    expect(bytesToMbExact(158_000_000)).toBe('158.000000')
  })

  it('rejects an unsafe integer instead of formatting it lossily', () => {
    expect(() => bytesToMbExact(Number.MAX_SAFE_INTEGER + 1)).toThrow(RangeError)
  })
})

describe('adaptive byte display (spec §3-2)', () => {
  it('shows small outputs as B or KB, not 0.00 MB', () => {
    // The readability test sizes from the spec.
    expect(formatBytesAdaptive(40_983)).toBe('40.98 KB')
    expect(formatBytesAdaptive(74_705)).toBe('74.71 KB')
    // A tiny non-zero value never collapses to 0.00 of a bigger unit.
    expect(formatBytesAdaptive(512)).toBe('512 B')
    expect(formatBytesAdaptive(1)).toBe('1 B')
  })

  it('keeps large outputs and the total budget in MB / GB (decimal, not MiB)', () => {
    // Golden capacity stays identical to the MB display it replaced.
    expect(formatBytesAdaptive(526_555_476)).toBe('526.56 MB')
    expect(formatBytesAdaptive(522_000_000)).toBe('522.00 MB')
    expect(formatBytesAdaptive(2_500_000_000)).toBe('2.50 GB')
    // 1 MB is exactly 1,000,000 B (not 1,048,576).
    expect(formatBytesAdaptive(1_000_000)).toBe('1.00 MB')
  })

  it('renders zero as 0 B', () => {
    expect(formatBytesAdaptive(0)).toBe('0 B')
  })

  it('gives exact grouped bytes for detail/title', () => {
    expect(bytesToExactBytes(40_983)).toBe('40,983 B')
    expect(bytesToExactBytes(526_555_476)).toBe('526,555,476 B')
  })

  it('refuses to format an unsafe integer lossily', () => {
    expect(() => formatBytesAdaptive(Number.MAX_SAFE_INTEGER + 1)).toThrow(RangeError)
  })
})

describe('microsecond -> second conversion', () => {
  it('keeps full precision (golden: 4,212,443,830 us)', () => {
    expect(microsToSecondsExact(4_212_443_830)).toBe('4212.443830')
  })

  it('rounds for display to 3 decimals', () => {
    expect(microsToSecondsDisplay(4_212_443_830)).toBe('4212.444')
  })

  it('formats a gap as h/m/s (golden max gap 25,394,651,015 us)', () => {
    // 25,394,651,015 us = 25394.651015 s = 7h 3m 14s
    expect(microsToHms(25_394_651_015)).toBe('7h 3m 14s')
  })
})
