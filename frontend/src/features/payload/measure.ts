// Local size measurement for model outputs.
//
// The UI never uploads a model output's content: it measures the size in the browser and sends only
// the byte metadata (FRONTEND_IMPLEMENTATION_SPEC §8, FE-13). Pasted text is measured as its raw
// UTF-8 byte length with no whitespace stripping, JSON normalisation or compression (FE-12); files
// are measured by File.size without reading their bytes.

const encoder = new TextEncoder()

/** Raw UTF-8 byte length of a string, exactly as it would be transmitted. */
export function utf8ByteSize(text: string): number {
  return encoder.encode(text).length
}

export interface MeasuredFile {
  name: string
  sizeBytes: number
}

/** Size a picked file by its metadata only — its contents are never read or sent. */
export function measureFile(file: File): MeasuredFile {
  return { name: file.name, sizeBytes: file.size }
}

/** Decimal byte factors for the assumed-size unit picker (MB = 1,000,000 B, never MiB — ADR-0005). */
export const ASSUMED_UNIT_FACTORS: Record<string, number> = {
  B: 1,
  KB: 1_000,
  MB: 1_000_000,
  GB: 1_000_000_000,
}

/**
 * Convert an assumed size (value string + unit) to a positive integer byte count, or null if it does
 * not resolve to a safe positive integer. A fractional value that lands on a whole byte count is
 * accepted (e.g. "2.5" MB -> 2,500,000 B); one that does not (e.g. "0.5" B) is rejected rather than
 * silently rounded, keeping the exact-integer byte contract (FE-27).
 */
export function computeAssumedBytes(value: string, unit: string): number | null {
  const trimmed = value.trim()
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null
  const factor = ASSUMED_UNIT_FACTORS[unit] ?? 1
  const bytes = Number(trimmed) * factor
  if (!Number.isInteger(bytes) || !Number.isSafeInteger(bytes) || bytes <= 0) return null
  return bytes
}
