// A labelled text input for an exact numeric or string field.
//
// Values are always edited as strings and converted on submit, never on keystroke
// (FRONTEND_IMPLEMENTATION_SPEC §7). The field shows its unit and a short help line, and wires
// label/description/error together for assistive tech (§8).

import { useId } from 'react'

import { EvidenceDot } from './EvidenceDot'
import type { EvidenceMark } from './evidence'

export interface UnitFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  unit?: string
  help?: string
  error?: string | null
  inputMode?: 'numeric' | 'text'
  monospace?: boolean
  disabled?: boolean
  /** Placeholder shown when the field is empty (e.g. an example value for a new entry). */
  placeholder?: string
  /** Optional measured/provisional/assumption mark shown as a clickable dot next to the label. */
  evidence?: EvidenceMark
  onCycleEvidence?: (next: EvidenceMark) => void
}

export function UnitField({
  label,
  value,
  onChange,
  unit,
  help,
  error,
  inputMode = 'text',
  monospace,
  disabled,
  placeholder,
  evidence,
  onCycleEvidence,
}: UnitFieldProps) {
  const id = useId()
  const helpId = `${id}-help`
  const errorId = `${id}-error`
  const describedBy = [help ? helpId : null, error ? errorId : null].filter(Boolean).join(' ')
  return (
    <div
      className={`unit-field${error ? ' unit-field--error' : ''}`}
      data-evidence={onCycleEvidence ? (evidence ?? 'unset') : undefined}
    >
      <label htmlFor={id}>
        {onCycleEvidence ? (
          <EvidenceDot mark={evidence ?? 'unset'} onChange={onCycleEvidence} fieldLabel={label} />
        ) : null}
        {label}
        {unit ? <span className="unit-field__unit"> ({unit})</span> : null}
      </label>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode={inputMode}
        placeholder={placeholder}
        aria-describedby={describedBy || undefined}
        aria-invalid={error ? true : undefined}
        className={monospace ? 'mono' : undefined}
        disabled={disabled}
        spellCheck={false}
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
