// Exact unit conversions for display.
//
// The backend is the source of truth for every number. These helpers only *display*
// integer domain quantities; they must never lose precision the way `value / 1_000_000` would for
// large integers. So the fractional part is computed with integer remainder math, and the
// unrounded and rounded forms are kept separate: comparisons use the exact form, screens use the
// rounded one. MB here means 1,000,000 bytes (decimal), never MiB.

const BYTES_PER_KB = 1_000
const BYTES_PER_MB = 1_000_000
const BYTES_PER_GB = 1_000_000_000
const MICROSECONDS_PER_SECOND = 1_000_000

const GROUP = new Intl.NumberFormat('en-US')

/** Exact integer bytes with thousands separators for detail/title, e.g. 40983 -> "40,983 B". */
export function bytesToExactBytes(bytes: number): string {
  if (!Number.isSafeInteger(bytes)) {
    throw new RangeError(`byte count ${bytes} is not a safe integer`)
  }
  return `${GROUP.format(bytes)} B`
}

/**
 * Adaptive decimal byte display: B below 1 KB, then KB / MB / GB (each 1,000× the previous, decimal —
 * MB is 1,000,000 B, never MiB). The unit is chosen so a non-zero value never collapses
 * to "0.00" — small outputs read as B or KB, while large outputs and the total budget read as MB or
 * GB (spec §3-2). Zero renders "0 B". For the exact integer, use {@link bytesToExactBytes} in detail.
 */
export function formatBytesAdaptive(bytes: number, decimals = 2): string {
  if (!Number.isSafeInteger(bytes)) {
    throw new RangeError(`byte count ${bytes} is not a safe integer`)
  }
  const abs = Math.abs(bytes)
  const scale = 10 ** decimals
  const steps: [number, string][] = [
    [BYTES_PER_GB, 'GB'],
    [BYTES_PER_MB, 'MB'],
    [BYTES_PER_KB, 'KB'],
  ]
  for (const [div, suffix] of steps) {
    if (abs >= div) {
      // Round on the exact rational, not on a pre-divided float (mirrors bytesToMbDisplay).
      const rounded = Math.round((bytes / div) * scale) / scale
      return `${rounded.toFixed(decimals)} ${suffix}`
    }
  }
  return bytesToExactBytes(bytes)
}

/** Split a non-negative integer into whole units and a zero-padded 6-digit micro remainder. */
function splitMicro(value: number, perUnit: number): { whole: number; frac6: string } {
  if (!Number.isSafeInteger(value)) {
    throw new RangeError(`value ${value} is not a safe integer; refusing to format it lossily`)
  }
  const negative = value < 0
  const abs = Math.abs(value)
  const whole = Math.floor(abs / perUnit)
  const frac = abs % perUnit
  const frac6 = String(frac).padStart(6, '0')
  return { whole: negative ? -whole : whole, frac6 }
}

/** Exact decimal string with full micro precision, e.g. 526555476 B -> "526.555476". */
export function bytesToMbExact(bytes: number): string {
  const { whole, frac6 } = splitMicro(bytes, BYTES_PER_MB)
  return `${whole}.${frac6}`
}

/** Rounded MB string for compact display, e.g. 526555476 B -> "526.56". */
export function bytesToMbDisplay(bytes: number, decimals = 2): string {
  if (!Number.isSafeInteger(bytes)) {
    throw new RangeError(`byte count ${bytes} is not a safe integer`)
  }
  // Round on the exact rational, not on a pre-divided float.
  const scale = 10 ** decimals
  const rounded = Math.round((bytes / BYTES_PER_MB) * scale) / scale
  return rounded.toFixed(decimals)
}

/**
 * Best-effort MB hint from an in-progress form string. Returns null (rather than throwing) for an
 * empty, non-integer, or out-of-safe-range value, so a live-editing hint never crashes the editor.
 */
export function bytesStringToMbHint(raw: string): string | null {
  const trimmed = raw.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const value = Number(trimmed)
  if (!Number.isSafeInteger(value)) return null
  return bytesToMbDisplay(value)
}

/**
 * Best-effort adaptive size hint from an in-progress form string (e.g. "40983" -> "40.98 KB"),
 * or null for an empty/non-integer/out-of-range value so a live editor never crashes.
 */
export function bytesStringToAdaptiveHint(raw: string): string | null {
  const trimmed = raw.trim()
  if (!/^\d+$/.test(trimmed)) return null
  const value = Number(trimmed)
  if (!Number.isSafeInteger(value)) return null
  return formatBytesAdaptive(value)
}

/** Exact seconds string with microsecond precision, e.g. 4212443830 us -> "4212.443830". */
export function microsToSecondsExact(micros: number): string {
  const { whole, frac6 } = splitMicro(micros, MICROSECONDS_PER_SECOND)
  return `${whole}.${frac6}`
}

/** Rounded seconds for compact display. */
export function microsToSecondsDisplay(micros: number, decimals = 3): string {
  if (!Number.isSafeInteger(micros)) {
    throw new RangeError(`microsecond count ${micros} is not a safe integer`)
  }
  const scale = 10 ** decimals
  const rounded = Math.round((micros / MICROSECONDS_PER_SECOND) * scale) / scale
  return rounded.toFixed(decimals)
}

/** Human duration from microseconds, e.g. "6h 51m 12s" — for gaps and long spans. */
export function microsToHms(micros: number): string {
  if (!Number.isSafeInteger(micros)) {
    throw new RangeError(`microsecond count ${micros} is not a safe integer`)
  }
  const totalSeconds = Math.floor(micros / MICROSECONDS_PER_SECOND)
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  const parts: string[] = []
  if (h > 0) parts.push(`${h}h`)
  if (h > 0 || m > 0) parts.push(`${m}m`)
  parts.push(`${s}s`)
  return parts.join(' ')
}
