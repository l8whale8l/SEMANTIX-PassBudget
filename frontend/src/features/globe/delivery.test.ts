import { describe, expect, it } from 'vitest'
import { buildFlights, deliveryProgressAt, toSegments, type PayloadMeta } from './delivery'
import type { PayloadAllocation } from '../../shared/api/types'

function alloc(payload_key: string, start: string, end: string, allocated_bytes: number): PayloadAllocation {
  return {
    payload_key,
    session_key: 's',
    station_key: 'g',
    allocation_ordinal: 0,
    logical_offset_start: 0,
    start,
    end,
    allocated_bytes,
    remaining_bytes_after: 0,
    modeled_tx_complete_at: end,
  }
}

const metas: PayloadMeta[] = [
  { payloadKey: 'A', name: 'A', emoji: '🔥', totalBytes: 300, readyAtMs: Date.parse('2026-09-03T00:00:00Z') },
]

// Two segments for A: [01:00–01:10] 100 B, then [02:00–02:10] 200 B. A gap sits between them.
const segments = toSegments([
  alloc('A', '2026-09-03T01:00:00Z', '2026-09-03T01:10:00Z', 100),
  alloc('A', '2026-09-03T02:00:00Z', '2026-09-03T02:10:00Z', 200),
])

const at = (iso: string) => Date.parse(iso)

describe('deliveryProgressAt (spec §8)', () => {
  it('is zero before the first segment ends (planned, not started)', () => {
    const [row] = deliveryProgressAt(segments, metas, at('2026-09-03T01:05:00Z'))
    expect(row.plannedBytes).toBe(0)
    expect(row.status).toBe('WAITING')
  })

  it('steps up only when a segment has fully completed (end <= T), and carries the emoji', () => {
    const [row] = deliveryProgressAt(segments, metas, at('2026-09-03T01:10:00Z'))
    expect(row.plannedBytes).toBe(100)
    expect(row.status).toBe('IN_PROGRESS')
    expect(row.emoji).toBe('🔥')
  })

  it('does not increase during the gap between segments', () => {
    const a = deliveryProgressAt(segments, metas, at('2026-09-03T01:30:00Z'))[0]
    const b = deliveryProgressAt(segments, metas, at('2026-09-03T01:59:00Z'))[0]
    expect(a.plannedBytes).toBe(100)
    expect(b.plannedBytes).toBe(100) // unchanged across the gap
  })

  it('reaches the full total by the end and reports it complete', () => {
    const [row] = deliveryProgressAt(segments, metas, at('2026-09-03T03:00:00Z'))
    expect(row.plannedBytes).toBe(300)
    expect(row.fraction).toBe(1)
    expect(row.status).toBe('COMPLETE')
  })

  it('reproduces the same value when time moves backward (deterministic in T)', () => {
    const forward = deliveryProgressAt(segments, metas, at('2026-09-03T02:10:00Z'))[0].plannedBytes
    const back = deliveryProgressAt(segments, metas, at('2026-09-03T01:10:00Z'))[0].plannedBytes
    expect(forward).toBe(300)
    expect(back).toBe(100)
  })

  it('shows 생성 전 before the output is ready', () => {
    const early: PayloadMeta[] = [{ ...metas[0], readyAtMs: Date.parse('2026-09-03T05:00:00Z') }]
    const [row] = deliveryProgressAt(segments, early, at('2026-09-03T01:00:00Z'))
    expect(row.status).toBe('PRE_READY')
  })
})

describe('buildFlights (emoji beam flights)', () => {
  it('makes one flight per valid allocation, carrying the chosen emoji', () => {
    const flights = buildFlights(
      [
        alloc('A', '2026-09-03T01:00:00Z', '2026-09-03T01:10:00Z', 100),
        alloc('B', '2026-09-03T02:00:00Z', '2026-09-03T02:10:00Z', 200),
      ],
      new Map([['A', '🔥'], ['B', '🚢']]),
    )
    expect(flights).toHaveLength(2)
    expect(flights[0]).toMatchObject({ payloadKey: 'A', emoji: '🔥', stationKey: 'g' })
    expect(flights[0].startMs).toBe(Date.parse('2026-09-03T01:00:00Z'))
  })

  it('falls back to a default emoji when a key has none, and drops zero/negative-length segments', () => {
    const flights = buildFlights(
      [
        alloc('A', '2026-09-03T01:00:00Z', '2026-09-03T01:10:00Z', 100),
        alloc('Z', '2026-09-03T03:00:00Z', '2026-09-03T03:00:00Z', 0), // zero-length → dropped
      ],
      new Map(),
    )
    expect(flights).toHaveLength(1)
    expect(flights[0].emoji).toBe('📦')
  })
})
