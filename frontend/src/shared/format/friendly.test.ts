import { describe, expect, it } from 'vitest'
import {
  decimalToScaledInt,
  degToUdeg,
  efficiencyToPct,
  fractionToDecimal,
  mbpsToRate,
  mmToM,
  mToMm,
  pctToEfficiency,
  PrecisionError,
  rateToMbps,
  reduceFraction,
  scaledIntToDecimal,
  udegToDeg,
} from './friendly'

describe('degrees <-> micro-degrees', () => {
  it('converts exactly for the golden station latitude 37.6 deg', () => {
    expect(degToUdeg('lat', '37.6')).toBe(37_600_000)
    expect(udegToDeg(37_600_000)).toBe('37.6')
  })
  it('round-trips whole degrees and zero', () => {
    expect(degToUdeg('lon', '127')).toBe(127_000_000)
    expect(udegToDeg(0)).toBe('0')
    expect(degToUdeg('lat', '0')).toBe(0)
  })
  it('keeps six fractional digits', () => {
    expect(degToUdeg('x', '12.345678')).toBe(12_345_678)
    expect(udegToDeg(12_345_678)).toBe('12.345678')
  })
  it('rejects more precision than micro-degrees can hold, instead of rounding', () => {
    expect(() => degToUdeg('x', '12.3456789')).toThrow(PrecisionError)
  })
  it('handles negatives (southern latitude / western longitude)', () => {
    expect(degToUdeg('lat', '-33.865')).toBe(-33_865_000)
    expect(udegToDeg(-33_865_000)).toBe('-33.865')
  })
})

describe('metres <-> millimetres (ellipsoidal height)', () => {
  it('converts the golden 100000 mm to 100 m', () => {
    expect(mmToM(100_000)).toBe('100')
    expect(mToMm('height', '100')).toBe(100_000)
  })
  it('keeps millimetre precision and rejects beyond it', () => {
    expect(mToMm('h', '0.001')).toBe(1)
    expect(() => mToMm('h', '0.0001')).toThrow(PrecisionError)
  })
})

describe('Mbps <-> bits/second', () => {
  it('converts the golden 2,000,000 bits/s to 2 Mbps and back', () => {
    expect(rateToMbps(2_000_000, 1)).toBe('2')
    expect(mbpsToRate('rate', '2')).toEqual({ numerator: 2_000_000, denominator: 1 })
  })
  it('handles fractional Mbps exactly', () => {
    expect(mbpsToRate('rate', '2.5')).toEqual({ numerator: 2_500_000, denominator: 1 })
    expect(mbpsToRate('rate', '0.5')).toEqual({ numerator: 500_000, denominator: 1 })
    expect(rateToMbps(500_000, 1)).toBe('0.5')
  })
  it('returns null when a rate is not exactly representable as decimal Mbps', () => {
    // 1_000_000 bits / 3 s = 0.333... Mbps -> keep the fraction, use advanced field.
    expect(rateToMbps(1_000_000, 3)).toBeNull()
  })
})

describe('percent <-> efficiency fraction', () => {
  it('converts the golden 1/2 to 50% and back', () => {
    expect(efficiencyToPct(1, 2)).toBe('50')
    expect(pctToEfficiency('eff', '50')).toEqual({ numerator: 1, denominator: 2 })
  })
  it('handles clean fractional percents exactly', () => {
    expect(pctToEfficiency('eff', '12.5')).toEqual({ numerator: 1, denominator: 8 })
    expect(efficiencyToPct(1, 8)).toBe('12.5')
  })
  it('returns null for a non-terminating efficiency like 1/3', () => {
    expect(efficiencyToPct(1, 3)).toBeNull()
  })
})

describe('helpers', () => {
  it('reduces fractions with positive denominator', () => {
    expect(reduceFraction(50, 100)).toEqual({ numerator: 1, denominator: 2 })
    expect(reduceFraction(2, -4)).toEqual({ numerator: -1, denominator: 2 })
  })
  it('fractionToDecimal returns null for non-terminating', () => {
    expect(fractionToDecimal(1, 3)).toBeNull()
    expect(fractionToDecimal(3, 8)).toBe('0.375')
  })
  it('scaledIntToDecimal / decimalToScaledInt are inverse', () => {
    expect(scaledIntToDecimal(decimalToScaledInt('x', '5.04', 6), 6)).toBe('5.04')
  })
})
