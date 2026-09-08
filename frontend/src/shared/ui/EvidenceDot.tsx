// A small clickable colour dot shown next to an input's label, marking whether the value is measured
// (green), provisional (amber), an assumption (red), or unmarked (grey). Clicking cycles the state.
// It is a bookkeeping aid only and never affects the calculation (see shared/ui/evidence.ts).

import { cycleEvidence, evidenceMeta, type EvidenceMark } from './evidence'

export interface EvidenceDotProps {
  mark: EvidenceMark
  onChange: (next: EvidenceMark) => void
  /** Field name, folded into the tooltip/aria so the control is identifiable out of context. */
  fieldLabel: string
}

export function EvidenceDot({ mark, onChange, fieldLabel }: EvidenceDotProps) {
  const meta = evidenceMeta(mark)
  const title = `${fieldLabel}: ${meta.label} — 클릭하면 실측/잠정/가정/미지정으로 전환`
  return (
    <button
      type="button"
      className={`evidence-dot evidence-dot--${meta.tone}`}
      onClick={() => onChange(cycleEvidence(mark))}
      title={title}
      aria-label={title}
    >
      <span className="sr-only">{meta.label}</span>
    </button>
  )
}
