// Time-based delivery progress (spec §8), derived ONLY from the run's existing result.
//
// The backend already returns `payload_allocations`: per-output transfer segments, each with a
// [start, end] time and the bytes moved in that segment (see F8_DELIVERY_PROGRESS_INVESTIGATION).
// The planned amount delivered by a selected time T is the sum of `allocated_bytes` over the segments
// whose `end` has passed T — a step at each completed allocation boundary. This is the contract-safe
// baseline: no interpolation inside a segment, no invented progress, and no increase during a gap
// (there are no segments there). The end-of-window cumulative equals the final allocated total, which
// matches `payload_progress.allocated_bytes`. This is display only; it never changes a computed value.

import type { PayloadAllocation } from '../../shared/api/types'

export type DeliveryStatus = 'PRE_READY' | 'WAITING' | 'IN_PROGRESS' | 'COMPLETE'

export interface PayloadMeta {
  payloadKey: string
  name: string
  /** The output's chosen emoji (same one that streams down the beam) — display only. */
  emoji: string
  totalBytes: number
  /** ready_at in epoch ms; before this the output does not exist yet. */
  readyAtMs: number
}

export interface DeliveryRow {
  payloadKey: string
  name: string
  emoji: string
  plannedBytes: number
  totalBytes: number
  /** plannedBytes / totalBytes clamped to [0, 1] (0 when total is 0). */
  fraction: number
  status: DeliveryStatus
}

/** Pre-parse allocation end times to ms once, so scrubbing the clock does not re-parse every frame. */
export interface AllocationSegment {
  payloadKey: string
  endMs: number
  allocatedBytes: number
}

export function toSegments(allocations: PayloadAllocation[]): AllocationSegment[] {
  return allocations.map((a) => ({
    payloadKey: a.payload_key,
    endMs: Date.parse(a.end),
    allocatedBytes: a.allocated_bytes,
  }))
}

/**
 * Planned delivery for each output at the selected instant `atMs`: the sum of completed allocation
 * segments (`endMs <= atMs`), clamped to the output's total. Status is derived from that planned
 * amount and the ready time — always the *planned* amount at the selected time, never a real receipt.
 */
export function deliveryProgressAt(
  segments: AllocationSegment[],
  metas: PayloadMeta[],
  atMs: number,
): DeliveryRow[] {
  return metas.map((meta) => {
    let planned = 0
    for (const seg of segments) {
      if (seg.payloadKey === meta.payloadKey && seg.endMs <= atMs) planned += seg.allocatedBytes
    }
    const plannedBytes = Math.min(planned, meta.totalBytes)
    const fraction = meta.totalBytes > 0 ? Math.min(1, Math.max(0, plannedBytes / meta.totalBytes)) : 0
    const status: DeliveryStatus =
      atMs < meta.readyAtMs
        ? 'PRE_READY'
        : meta.totalBytes > 0 && plannedBytes >= meta.totalBytes
          ? 'COMPLETE'
          : plannedBytes > 0
            ? 'IN_PROGRESS'
            : 'WAITING'
    return { payloadKey: meta.payloadKey, name: meta.name, emoji: meta.emoji, plannedBytes, totalBytes: meta.totalBytes, fraction, status }
  })
}

/** One in-flight transfer segment to visualise: an output's emoji streaming down a station's beam
 *  during [startMs, endMs] (from a payload allocation). Display only — never a computed value. */
export interface Flight {
  payloadKey: string
  emoji: string
  stationKey: string
  startMs: number
  endMs: number
}

/**
 * Build the beam "flights" from the run's allocations + each output's chosen emoji: one flight per
 * allocation segment, so at any instant only the allocations active then stream their emoji down the
 * satellite→station beam. Segments with unparseable times are dropped.
 */
export function buildFlights(
  allocations: PayloadAllocation[],
  emojiByKey: ReadonlyMap<string, string>,
): Flight[] {
  const flights: Flight[] = []
  for (const a of allocations) {
    const startMs = Date.parse(a.start)
    const endMs = Date.parse(a.end)
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) continue
    flights.push({
      payloadKey: a.payload_key,
      emoji: emojiByKey.get(a.payload_key) ?? '📦',
      stationKey: a.station_key,
      startMs,
      endMs,
    })
  }
  return flights
}

const STATUS_LABEL: Record<DeliveryStatus, string> = {
  PRE_READY: '생성 전',
  WAITING: '대기',
  IN_PROGRESS: '진행 중',
  COMPLETE: '완료(계획상)',
}

export function deliveryStatusLabel(status: DeliveryStatus): string {
  return STATUS_LABEL[status]
}
