// JSON / integer helpers shared by the input and result layers.

/**
 * The maximum integer a JSON number field can carry through `JSON.parse`/`stringify` losslessly.
 * The backend accepts arbitrarily large integers (byte counts, microdegrees, mu); JavaScript
 * numbers are only exact up to 2^53 - 1. Rather than silently corrupt a value beyond that, we
 * refuse it explicitly and keep the user's original string (FRONTEND_IMPLEMENTATION_SPEC §7,
 * FE-27). A later revision may add a lossless big-integer transport contract.
 */
export const MAX_SAFE_INT = Number.MAX_SAFE_INTEGER

export class UnsafeIntegerError extends Error {
  readonly fieldPath: string
  readonly rawValue: string
  constructor(fieldPath: string, rawValue: string) {
    super(
      `Value at ${fieldPath} exceeds the lossless integer range (|x| <= ${MAX_SAFE_INT}). ` +
        `Refusing to send it rather than round it silently.`,
    )
    this.name = 'UnsafeIntegerError'
    this.fieldPath = fieldPath
    this.rawValue = rawValue
  }
}

/**
 * Parse a user-edited string into an exact integer, or throw. Empty/……non-integer syntax and
 * out-of-safe-range values are rejected; the raw string is carried on the error so the form can
 * keep it. This is the only place a form string becomes a number for the request body.
 */
export function parseIntegerField(fieldPath: string, raw: string): number {
  const trimmed = raw.trim()
  if (!/^-?\d+$/.test(trimmed)) {
    throw new Error(`Value at ${fieldPath} must be an integer, got "${raw}".`)
  }
  const value = Number(trimmed)
  if (!Number.isSafeInteger(value)) {
    throw new UnsafeIntegerError(fieldPath, raw)
  }
  return value
}

/** Deterministic JSON with sorted keys. Used only for local draft identity/equality. */
export function stableStringify(value: unknown): string {
  return JSON.stringify(sortKeys(value))
}

export function deepEqual(a: unknown, b: unknown): boolean {
  return stableStringify(a) === stableStringify(b)
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys)
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      out[key] = sortKeys((value as Record<string, unknown>)[key])
    }
    return out
  }
  return value
}
