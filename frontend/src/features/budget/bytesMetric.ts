import { formatBytesAdaptive } from '../../shared/format/units'

/**
 * Format a byte metric that may be null. A null is NOT unconditionally "0" or "not applicable": its
 * meaning depends on the metric and the analysis mode (correction 2). In NETWORK_ONLY there is no
 * payload layer, so allocation/stranded metrics are genuinely not applicable; elsewhere a null is
 * "unknown/not provided" rather than an invented zero.
 */
export function bytesMetric(
  value: number | null | undefined,
  mode: string,
  naReason?: string,
): string {
  if (value === null || value === undefined) {
    if (mode === 'NETWORK_ONLY' && naReason) return `해당 없음 · ${naReason}`
    return '해당 없음 (제공되지 않음)'
  }
  if (!Number.isSafeInteger(value)) return '표시 불가 (정밀도 손실)'
  return formatBytesAdaptive(value)
}
