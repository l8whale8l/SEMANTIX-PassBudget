// UTC instant handling.
//
// The backend stores and compares time in exact UTC microseconds. A JavaScript `Date` only holds
// milliseconds, so parsing "2026-09-03T03:11:44.916905Z" into a Date and back would silently drop
// the 905 microsecond tail (FRONTEND_IMPLEMENTATION_SPEC §7). We therefore treat an instant as its
// canonical string and format it by string surgery, never by Date round-tripping.

export interface UtcInstant {
  /** The original, unmodified source string. */
  readonly raw: string
  readonly year: number
  readonly month: number
  readonly day: number
  readonly hour: number
  readonly minute: number
  readonly second: number
  /** Zero-padded fractional-seconds digits exactly as supplied (may be empty). */
  readonly fraction: string
}

// Accepts the forms the API emits and accepts: date, T, time, optional fractional seconds, Z.
const UTC_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$/

export function parseUtcInstant(value: string): UtcInstant {
  const match = UTC_RE.exec(value)
  if (!match) {
    throw new Error(`not a UTC instant (expected e.g. 2026-09-03T00:00:00Z): ${value}`)
  }
  const [, y, mo, d, h, mi, s, frac] = match
  return {
    raw: value,
    year: Number(y),
    month: Number(mo),
    day: Number(d),
    hour: Number(h),
    minute: Number(mi),
    second: Number(s),
    fraction: frac ?? '',
  }
}

export function isUtcInstant(value: string): boolean {
  return UTC_RE.test(value)
}

/**
 * Display an instant in UTC without precision loss, e.g. "2026-09-03 03:11:44.916905 UTC".
 * `fractionDigits` trims or pads only the display copy; the stored value is never changed.
 */
export function formatUtc(value: string, fractionDigits?: number): string {
  const t = parseUtcInstant(value)
  const date = `${pad(t.year, 4)}-${pad(t.month, 2)}-${pad(t.day, 2)}`
  const time = `${pad(t.hour, 2)}:${pad(t.minute, 2)}:${pad(t.second, 2)}`
  let frac = t.fraction
  if (fractionDigits !== undefined) {
    frac = frac.slice(0, fractionDigits).padEnd(fractionDigits, '0')
  }
  return frac ? `${date} ${time}.${frac} UTC` : `${date} ${time} UTC`
}

/** Just the clock part, e.g. "03:11:44" — for dense pass tables. */
export function formatUtcClock(value: string): string {
  const t = parseUtcInstant(value)
  return `${pad(t.hour, 2)}:${pad(t.minute, 2)}:${pad(t.second, 2)}`
}

function epochSeconds(t: UtcInstant): number {
  return Math.floor(Date.UTC(t.year, t.month - 1, t.day, t.hour, t.minute, t.second) / 1000)
}

/** Korean duration from whole seconds, e.g. 86400 -> "24시간", 5400 -> "1시간 30분". */
function durationKo(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  const parts: string[] = []
  if (h > 0) parts.push(`${h}시간`)
  if (m > 0) parts.push(`${m}분`)
  if (s > 0) parts.push(`${s}초`)
  return parts.length ? parts.join(' ') : '0초'
}

/**
 * Human analysis-window label: date range + duration + timezone, e.g.
 * "9월 3일 → 9월 4일 · 24시간 · UTC" (spec §3-2). The window bounds are second-aligned, so the
 * *duration label* is computed on whole seconds; any fractional tail on the stored instants is
 * untouched. Same start/end date still shows both sides so the arrow reads consistently.
 */
export function formatAnalysisWindow(startIso: string, endIso: string): string {
  const s = parseUtcInstant(startIso)
  const e = parseUtcInstant(endIso)
  const start = `${s.month}월 ${s.day}일`
  const end = `${e.month}월 ${e.day}일`
  const durSec = Math.max(0, epochSeconds(e) - epochSeconds(s))
  return `${start} → ${end} · ${durationKo(durSec)} · UTC`
}

function pad(n: number, width: number): string {
  return String(n).padStart(width, '0')
}
