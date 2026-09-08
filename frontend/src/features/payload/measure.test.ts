import { describe, expect, it } from 'vitest'
import { computeAssumedBytes, utf8ByteSize } from './measure'

describe('utf8ByteSize', () => {
  it('measures raw UTF-8 bytes, not code points', () => {
    expect(utf8ByteSize('abc')).toBe(3)
    expect(utf8ByteSize('가')).toBe(3) // one Hangul syllable = 3 UTF-8 bytes
  })
})

describe('computeAssumedBytes (spec §6 assumed-size input)', () => {
  it('converts whole values by decimal unit (MB = 1,000,000 B)', () => {
    expect(computeAssumedBytes('40983', 'B')).toBe(40_983)
    expect(computeAssumedBytes('2', 'MB')).toBe(2_000_000)
    expect(computeAssumedBytes('1', 'GB')).toBe(1_000_000_000)
  })

  it('accepts a fraction that lands on a whole byte count', () => {
    expect(computeAssumedBytes('2.5', 'MB')).toBe(2_500_000)
    expect(computeAssumedBytes('74.705', 'KB')).toBe(74_705)
  })

  it('rejects a value that is not a positive safe integer number of bytes', () => {
    expect(computeAssumedBytes('0.5', 'B')).toBeNull() // half a byte
    expect(computeAssumedBytes('0', 'MB')).toBeNull() // zero not allowed
    expect(computeAssumedBytes('', 'MB')).toBeNull()
    expect(computeAssumedBytes('abc', 'MB')).toBeNull()
    expect(computeAssumedBytes('-3', 'MB')).toBeNull()
  })
})
