// Friendly <-> canonical unit conversion for the input forms.
//
// Team members should not have to type micro-degrees, millimetres, or a bits/second numerator and
// denominator (FRONTEND_IMPLEMENTATION_SPEC §7; correction 6). The forms therefore present degrees,
// metres, Mbps and percent, while the draft keeps the exact integer/rational canonical values as
// the source of truth. Conversion is exact string/integer arithmetic: a friendly value that cannot
// be represented in the canonical precision is REJECTED (never silently rounded), and a canonical
// value that cannot be shown exactly in the friendly unit returns `null` so the UI can fall back to
// the advanced exact field instead of lying with a rounded number.

export class PrecisionError extends Error {
  readonly fieldPath: string
  constructor(message: string, fieldPath: string) {
    super(message)
    this.name = 'PrecisionError'
    this.fieldPath = fieldPath
  }
}

const DECIMAL_RE = /^(-?)(\d+)(?:\.(\d+))?$/

/**
 * Parse a decimal string into an exact integer scaled by 10^scale. More than `scale` fractional
 * digits is a precision loss and is rejected. e.g. degrees->udeg uses scale 6: "37.6" -> 37_600_000.
 */
export function decimalToScaledInt(fieldPath: string, raw: string, scale: number): number {
  const match = DECIMAL_RE.exec(raw.trim())
  if (!match) {
    throw new PrecisionError(`${fieldPath}: 숫자를 입력하세요 ("${raw}").`, fieldPath)
  }
  const [, sign, intPart, fracPartRaw] = match
  const fracPart = fracPartRaw ?? ''
  if (fracPart.length > scale) {
    throw new PrecisionError(
      `${fieldPath}: 소수 ${scale}자리까지만 정확히 표현됩니다. 더 정밀한 값은 고급(정확값) 입력을 사용하세요.`,
      fieldPath,
    )
  }
  const digits = intPart + fracPart.padEnd(scale, '0')
  const value = Number(sign + digits.replace(/^0+(?=\d)/, ''))
  if (!Number.isSafeInteger(value)) {
    throw new PrecisionError(`${fieldPath}: 값이 안전 정수 범위를 벗어났습니다.`, fieldPath)
  }
  return value
}

/** Inverse of decimalToScaledInt: exact scaled integer -> trimmed decimal string. */
export function scaledIntToDecimal(value: number, scale: number): string {
  if (!Number.isSafeInteger(value)) {
    throw new PrecisionError(`값이 안전 정수가 아닙니다: ${value}`, 'value')
  }
  const negative = value < 0
  const digits = String(Math.abs(value)).padStart(scale + 1, '0')
  const intPart = digits.slice(0, digits.length - scale)
  let fracPart = scale > 0 ? digits.slice(digits.length - scale) : ''
  fracPart = fracPart.replace(/0+$/, '')
  const body = fracPart ? `${intPart}.${fracPart}` : intPart
  return negative ? `-${body}` : body
}

// -- specific geometry units -------------------------------------------------------------------

export const degToUdeg = (fieldPath: string, raw: string): number =>
  decimalToScaledInt(fieldPath, raw, 6)
export const udegToDeg = (udeg: number): string => scaledIntToDecimal(udeg, 6)
export const mToMm = (fieldPath: string, raw: string): number => decimalToScaledInt(fieldPath, raw, 3)
export const mmToM = (mm: number): string => scaledIntToDecimal(mm, 3)

// -- rational units (rate, efficiency) ---------------------------------------------------------

function gcd(a: number, b: number): number {
  a = Math.abs(a)
  b = Math.abs(b)
  while (b) {
    ;[a, b] = [b, a % b]
  }
  return a || 1
}

export interface Fraction {
  numerator: number
  denominator: number
}

/** Reduce a fraction to lowest terms with a positive denominator. */
export function reduceFraction(numerator: number, denominator: number): Fraction {
  if (denominator === 0) throw new PrecisionError('분모는 0일 수 없습니다.', 'denominator')
  const sign = denominator < 0 ? -1 : 1
  const g = gcd(numerator, denominator)
  return { numerator: (sign * numerator) / g, denominator: Math.abs(denominator) / g }
}

/**
 * Render a fraction as a terminating decimal string, or `null` when it does not terminate in
 * base 10 (e.g. 1/3). A `null` tells the UI to keep the exact fraction and use the advanced field.
 */
export function fractionToDecimal(numerator: number, denominator: number): string | null {
  const { numerator: n0, denominator: d0 } = reduceFraction(numerator, denominator)
  const negative = n0 < 0
  let n = Math.abs(n0)
  let d = d0
  let twos = 0
  let fives = 0
  while (d % 2 === 0) {
    d /= 2
    twos++
  }
  while (d % 5 === 0) {
    d /= 5
    fives++
  }
  if (d !== 1) return null // non-terminating
  const p = Math.max(twos, fives)
  const scaledNum = n * 2 ** (p - twos) * 5 ** (p - fives)
  if (!Number.isSafeInteger(scaledNum)) return null
  const body = scaledIntToDecimal(scaledNum, p)
  return negative && body !== '0' ? `-${body}` : body
}

/** Parse a decimal string into an exact fraction (numerator over 10^fractionDigits, reduced). */
function decimalToFraction(fieldPath: string, raw: string): Fraction {
  const match = DECIMAL_RE.exec(raw.trim())
  if (!match) throw new PrecisionError(`${fieldPath}: 숫자를 입력하세요 ("${raw}").`, fieldPath)
  const [, sign, intPart, fracPartRaw] = match
  const fracPart = fracPartRaw ?? ''
  const numerator = Number(sign + (intPart + fracPart).replace(/^0+(?=\d)/, ''))
  const denominator = 10 ** fracPart.length
  if (!Number.isSafeInteger(numerator) || !Number.isSafeInteger(denominator)) {
    throw new PrecisionError(`${fieldPath}: 값이 안전 정수 범위를 벗어났습니다.`, fieldPath)
  }
  return reduceFraction(numerator, denominator)
}

/** Mbps string -> exact bits/second fraction. "2" -> 2_000_000/1; "2.5" -> 2_500_000/1. */
export function mbpsToRate(fieldPath: string, raw: string): Fraction {
  const mbps = decimalToFraction(fieldPath, raw)
  // bits/s = mbps * 1_000_000
  return reduceFraction(mbps.numerator * 1_000_000, mbps.denominator)
}

/** bits/second fraction -> Mbps decimal string, or null if not exactly representable. */
export function rateToMbps(numeratorBits: number, denominatorSeconds: number): string | null {
  return fractionToDecimal(numeratorBits, denominatorSeconds * 1_000_000)
}

/** Percent string -> exact efficiency fraction. "50" -> 1/2; "12.5" -> 1/8. */
export function pctToEfficiency(fieldPath: string, raw: string): Fraction {
  const pct = decimalToFraction(fieldPath, raw)
  return reduceFraction(pct.numerator, pct.denominator * 100)
}

/** Efficiency fraction -> percent decimal string, or null if not exactly representable. */
export function efficiencyToPct(numerator: number, denominator: number): string | null {
  return fractionToDecimal(numerator * 100, denominator)
}
