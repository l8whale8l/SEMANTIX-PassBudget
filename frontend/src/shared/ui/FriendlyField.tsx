// A numeric field shown in a friendly unit (degrees, metres, Mbps, percent) that converts to the
// exact canonical integer/rational on every keystroke.
//
// The draft holds the canonical value as the source of truth. This field derives a friendly display
// string from it, and on edit converts back — rejecting (not rounding) any value the canonical
// precision cannot hold (correction 6, FE-27). If the canonical value cannot be represented exactly
// in the friendly unit (e.g. a 1/3 efficiency), the friendly input disables itself and points the
// user to the advanced exact field instead of showing a rounded lie.

import { useId, useState } from 'react'

import { EvidenceDot } from './EvidenceDot'
import type { EvidenceMark } from './evidence'

export interface FriendlyFieldProps {
  label: string
  unit: string
  help?: string
  /** The canonical source-of-truth string (e.g. "37600000" micro-degrees). */
  canonical: string
  /** Canonical -> friendly display string, or null if not exactly representable. */
  toFriendly: (canonical: string) => string | null
  /** Friendly text -> commit (parse + patch canonical). Must throw on invalid/imprecise input. */
  commit: (text: string) => void
  /** Placeholder shown when the field is empty (e.g. an example value for a new entry). */
  placeholder?: string
  /** Optional measured/provisional/assumption mark shown as a clickable dot next to the label. */
  evidence?: EvidenceMark
  onCycleEvidence?: (next: EvidenceMark) => void
}

export function FriendlyField({
  label,
  unit,
  help,
  canonical,
  toFriendly,
  commit,
  placeholder,
  evidence,
  onCycleEvidence,
}: FriendlyFieldProps) {
  const dot = onCycleEvidence ? (
    <EvidenceDot mark={evidence ?? 'unset'} onChange={onCycleEvidence} fieldLabel={label} />
  ) : null
  const dataEvidence = onCycleEvidence ? (evidence ?? 'unset') : undefined
  const id = useId()
  const derived = toFriendly(canonical)
  const [text, setText] = useState(derived ?? '')
  const [error, setError] = useState<string | null>(null)
  // Resync the display when the canonical value changes from elsewhere (preset load, advanced edit)
  // using React's "adjust state during render" pattern rather than an effect.
  const [prevCanonical, setPrevCanonical] = useState(canonical)
  if (canonical !== prevCanonical) {
    setPrevCanonical(canonical)
    if (derived !== null) {
      setText(derived)
      setError(null)
    }
  }

  // Only show the "표현 불가" disabled state when the canonical value HAS digits but cannot be shown in
  // this friendly unit. A blank canonical (a new entry) is an ordinary empty, editable field.
  if (derived === null && /[0-9]/.test(canonical)) {
    return (
      <div className="unit-field" data-evidence={dataEvidence}>
        <label htmlFor={id}>
          {dot}
          {label} <span className="unit-field__unit">({unit})</span>
        </label>
        <input id={id} value="" disabled aria-describedby={`${id}-na`} />
        <p id={`${id}-na`} className="unit-field__help">
          이 값은 {unit} 단위로 정확히 표현할 수 없습니다. 아래 “고급(정확값)”에서 편집하세요.
        </p>
      </div>
    )
  }

  const helpId = `${id}-help`
  const errorId = `${id}-error`
  const describedBy = [help ? helpId : null, error ? errorId : null].filter(Boolean).join(' ')
  return (
    <div className={`unit-field${error ? ' unit-field--error' : ''}`} data-evidence={dataEvidence}>
      <label htmlFor={id}>
        {dot}
        {label} <span className="unit-field__unit">({unit})</span>
      </label>
      <input
        id={id}
        value={text}
        inputMode="decimal"
        placeholder={placeholder}
        spellCheck={false}
        aria-describedby={describedBy || undefined}
        aria-invalid={error ? true : undefined}
        onChange={(e) => {
          const v = e.target.value
          setText(v)
          try {
            commit(v)
            setError(null)
          } catch (err) {
            setError((err as Error).message)
          }
        }}
      />
      {help ? (
        <p id={helpId} className="unit-field__help">
          {help}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="unit-field__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}
