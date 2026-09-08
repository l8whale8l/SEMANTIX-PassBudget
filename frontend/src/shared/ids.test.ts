import { describe, expect, it } from 'vitest'
import { nextEditId, uniqueStableKey } from './ids'

describe('nextEditId', () => {
  it('never repeats, even across many calls', () => {
    const ids = new Set(Array.from({ length: 100 }, () => nextEditId('gs')))
    expect(ids.size).toBe(100)
  })
})

describe('uniqueStableKey (correction 3)', () => {
  it('avoids a collision after add -> delete middle -> add again', () => {
    // Start with NEW-1, NEW-2, NEW-3; delete NEW-2; the next key must not reuse NEW-3 or collide.
    const existing = new Set(['SYN-GS-NEW-1', 'SYN-GS-NEW-3'])
    const key = uniqueStableKey(existing)
    expect(key).toBe('SYN-GS-NEW-2') // fills the gap rather than making a duplicate NEW-3
    expect(existing.has(key)).toBe(false)
  })

  it('returns NEW-1 when nothing exists', () => {
    expect(uniqueStableKey(new Set())).toBe('SYN-GS-NEW-1')
  })

  it('skips all taken keys', () => {
    const existing = new Set(['SYN-GS-NEW-1', 'SYN-GS-NEW-2', 'SYN-GS-NEW-3'])
    expect(uniqueStableKey(existing)).toBe('SYN-GS-NEW-4')
  })
})
